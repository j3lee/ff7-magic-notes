#!/usr/bin/env python3
"""magic_data.py MAGIC_DIR [--pc PC_DIR] [--out DIR] : walk every FF7 PS1 MAGIC overlay with the data model of
MAGIC-DATA-MODEL.md and report how many bytes each format explains, and every byte range it cannot place.

Python 3 standard library only. MAGIC_DIR holds the US disc's MAGIC/*.BIN; the code range of each overlay comes from
overlays.tsv next to this script (or --table). With --pc (the unpacked PC magic.lgp) blocks are cross-checked against
the PC release's named files and a table overlay -> named assets is written.

Every format is a function `find_*` that only claims bytes it has walked to the end with all checks passing; a byte
is claimed once. Nothing is claimed because of where it sits.
"""
import argparse
import collections
import csv
import hashlib
import json
import os
import struct
import sys

BASE = 0x801B0000
S16 = struct.Struct("<h")
U16 = struct.Struct("<H")
U32 = struct.Struct("<I")


def u16(d, o):
    return U16.unpack_from(d, o)[0]


def s16(d, o):
    return S16.unpack_from(d, o)[0]


def u32(d, o):
    return U32.unpack_from(d, o)[0]


class Overlay:
    def __init__(self, name, data, code_start, code_end):
        self.name = name
        self.d = data
        self.n = len(data)
        self.code_start = code_start
        self.code_end = code_end
        self.owner = bytearray(self.n)   # 0 = free, else index into self.claims + 1 (capped: see claim)
        self.claims = []                 # (start, end, kind, detail dict)
        self.code_refs = {}              # file offset -> list of code offsets that build its address
        self.data_ptrs = {}              # file offset -> list of data offsets holding a pointer to it
        self.calls_after = {}
        self.containers = []             # (file offset, bone count)            # file offset -> set of jal targets within 8 instructions of the reference

    def free(self, a, b):
        return a >= 0 and b <= self.n and a < b and not any(self.owner[a:b])

    def claim(self, a, b, kind, **detail):
        if not self.free(a, b):
            return False
        self.claims.append((a, b, kind, detail))
        self.owner[a:b] = b"\x01" * (b - a)
        return True

    def referenced(self, o):
        return o in self.code_refs or o in self.data_ptrs

    def how_found(self, o):
        r = []
        if o in self.code_refs:
            r.append("code")
        if o in self.data_ptrs:
            r.append("pointer")
        return "+".join(r) or "layout"


# ---- references: addresses built by code (lui + low half) and pointers stored in data ---------------------------

def scan_refs(ov):
    d, n = ov.d, ov.n
    regs = {}
    cs, ce = ov.code_start, min(ov.code_end, n)
    recent = []
    for o in range(cs, ce - 3, 4):
        w = u32(d, o)
        op = w >> 26
        rs, rt, imm = (w >> 21) & 31, (w >> 16) & 31, w & 0xFFFF
        simm = imm - 0x10000 if imm & 0x8000 else imm
        if op == 3:  # jal
            tgt = ((w & 0x3FFFFFF) << 2) | 0x80000000
            for (ro, fo) in recent:
                if o - ro <= 32:
                    ov.calls_after.setdefault(fo, set()).add(tgt)
            continue
        if op == 0x0F:  # lui
            regs[rt] = (imm << 16, o)
            continue
        addr = None
        if op == 0x09 and rs in regs and o - regs[rs][1] <= 64:      # addiu
            addr = (regs[rs][0] + simm) & 0xFFFFFFFF
            if rt == rs:
                del regs[rs]
        elif op == 0x0D and rs in regs and o - regs[rs][1] <= 64:    # ori
            addr = regs[rs][0] | imm
            if rt == rs:
                del regs[rs]
        elif op in (0x20, 0x21, 0x23, 0x24, 0x25, 0x28, 0x29, 0x2B) and rs in regs and o - regs[rs][1] <= 64:
            addr = (regs[rs][0] + simm) & 0xFFFFFFFF                # load / store through the lui register
        if addr is not None and BASE <= addr < BASE + n:
            fo = addr - BASE
            ov.code_refs.setdefault(fo, []).append(o)
            recent.append((o, fo))
            recent = recent[-8:]
    for o in list(range(0, cs - 3, 4)) + list(range(ce + (-ce % 4), n - 3, 4)):
        w = u32(d, o)
        if BASE <= w < BASE + n:
            ov.data_ptrs.setdefault(w - BASE, []).append(o)


# ---- TIM images ---------------------------------------------------------------------------------------------------

def parse_tim(d, o, end, allow_empty=False):
    """a PSX TIM at o: returns dict or None. Checks: id 0x10, flag, block lengths equal 12 + pixel bytes.
    allow_empty accepts a pixel block of 12 bytes (width 0), which the skeleton containers of the summons end with."""
    if o + 20 > end or u32(d, o) != 0x10:
        return None
    flag = u32(d, o + 4)
    if flag not in (0, 1, 2, 3, 8, 9, 10, 11):
        return None
    p = o + 8
    t = {"flag": flag, "bpp": (4, 8, 16, 24)[flag & 3]}
    if flag & 8:
        bnum = u32(d, p)
        x, y, w, h = struct.unpack_from("<HHHH", d, p + 4)
        if bnum != 12 + w * h * 2 or p + bnum > end or not (0 < w <= 256 and 0 < h <= 256) or x + w > 1024 or y + h > 512:
            return None
        t["clut"] = (x, y, w, h)
        p += bnum
    if p + 12 > end:
        return None
    bnum = u32(d, p)
    x, y, w, h = struct.unpack_from("<HHHH", d, p + 4)
    if bnum != 12 + w * h * 2 or p + bnum > end or not (w <= 1024 and h <= 512) or x + w > 1024 or y + h > 512:
        return None
    if w * h == 0 and not allow_empty:
        return None
    t["pix"] = (x, y, w, h)
    t["len"] = p + bnum - o
    return t


def find_tims(ov):
    o = 0
    while o + 20 <= ov.n:
        if o < ov.code_end and o >= ov.code_start:
            o = ov.code_end + (-ov.code_end % 4)
            continue
        t = parse_tim(ov.d, o, ov.n)
        if t and ov.claim(o, o + t["len"], "tim", found=ov.how_found(o), **{k: v for k, v in t.items() if k != "len"}):
            o += t["len"] + (-t["len"] % 4)
            continue
        o += 4


# ---- model block (BattleDrawModel layout) ---------------------------------------------------------------------------

LISTS = (("texTri", 0x10, 3, False), ("texQuad", 0x14, 4, True), ("colTri", 0x14, 3, False), ("colQuad", 0x18, 4, True))


def parse_mesh(d, o, end):
    """model block at o: u32 vertexBytes, vertices, four face lists. Every vertex pad must be 0 and every vertex
    reference of every record a multiple of 8 below vertexBytes. Returns dict or None."""
    if o + 20 > end:
        return None
    vb = u32(d, o)
    if vb < 8 or vb % 8 or vb > 0x8000 or o + 4 + vb + 16 > end:
        return None
    for k in range(vb // 8):
        if d[o + 4 + 8 * k + 6] or d[o + 4 + 8 * k + 7]:
            return None
    p = o + 4 + vb
    m = {"vertexBytes": vb, "nverts": vb // 8, "counts": [], "lists": [], "hdr_hi": []}
    tot = 0
    for name, size, nref, wide in LISTS:
        if p + 4 > end:
            return None
        cnt = u16(d, p)
        hi = u16(d, p + 2)
        if wide and hi:
            return None
        if cnt > 4000 or p + 4 + cnt * size > end:
            return None
        q = p + 4
        for k in range(cnt):
            for j in range(nref):
                v = u16(d, q + 2 * j)
                if v % 8 or v >= vb:
                    return None
            q += size
        m["counts"].append(cnt)
        m["hdr_hi"].append(hi)
        m["lists"].append((p + 4, cnt))
        tot += cnt
        p = q
    if tot == 0:
        return None
    m["len"] = p - o
    return m


def mesh_detail(ov, o, m):
    d = ov.d
    det = {"nverts": m["nverts"], "texTri": m["counts"][0], "texQuad": m["counts"][1], "colTri": m["counts"][2],
           "colQuad": m["counts"][3], "tpage": m["hdr_hi"][0], "hdr3_hi": m["hdr_hi"][2]}
    return det


def find_models(ov):
    """standalone model blocks: tried at every 4-aligned free offset that code or a data pointer addresses first,
    then at every remaining free offset"""
    cands = sorted(set(ov.code_refs) | set(ov.data_ptrs))
    for phase in (0, 1):
        offs = cands if phase == 0 else range(0, ov.n - 20, 4)
        for o in offs:
            if o % 4 or o >= ov.n or ov.owner[o]:
                continue
            m = parse_mesh(ov.d, o, ov.n)
            if not m or not ov.free(o, o + m["len"]):
                continue
            if phase == 1 and m["nverts"] < 3:
                continue
            ov.claim(o, o + m["len"], "model", found=ov.how_found(o), **mesh_detail(ov, o, m))


# ---- skeleton container (EffectModelHeader) ----------------------------------------------------------------------

class Bits:
    def __init__(self, b):
        self.b = b
        self.p = 0

    def get(self, n, signed=True):
        v = 0
        for _ in range(n):
            i = self.p >> 3
            byte = self.b[i] if i < len(self.b) else 0
            v = (v << 1) | ((byte >> (7 - (self.p & 7))) & 1)
            self.p += 1
        if signed and n and v >> (n - 1):
            v -= 1 << n
        return v


def decode_anim(rec, nbones, want_frames=False):
    """animation record: u16 frames, u16 size, u8 key, then a bit stream (most significant bit first). Returns
    (frames, size, key, bytes used by the stream, frames list or None). The stream is: frame 0 = three s16 root
    offsets, then 3 angles of (12 - key) bits per bone; later frames = per offset 1 flag bit then 7 or 16 bits of
    delta, per angle 1 flag bit, then if set a 3-bit length code and the delta."""
    if len(rec) < 5:
        return None
    frames, size, key = struct.unpack_from("<HHB", rec, 0)
    if key not in (0, 2, 4) or frames == 0:
        return None
    bs = Bits(rec[5:])
    pos = [bs.get(16) for _ in range(3)]
    rot = [bs.get(12 - key) << key for _ in range(3 * nbones)]
    out = [(tuple(pos), tuple(rot))] if want_frames else None
    for _ in range(1, frames):
        for i in range(3):
            pos[i] += bs.get(16) if bs.get(1, False) else bs.get(7)
        for i in range(3 * nbones):
            if bs.get(1, False):
                k = bs.get(3, False)
                if k == 0:
                    dlt = -1
                elif k == 7:
                    dlt = bs.get(12 - key)
                else:
                    dlt = bs.get(k)
                    dlt = dlt - (1 << (k - 1)) if dlt < 0 else dlt + (1 << (k - 1))
                rot[i] += dlt << key
        if want_frames:
            out.append((tuple(pos), tuple(rot)))
        if bs.p > 8 * (len(rec) - 5) + 64:
            return None
    return frames, size, key, (bs.p + 7) // 8, out


def anim_ok(rec, nbones):
    """decode and accept when the bit stream ends in the last byte the header's size gives (or the one before it)"""
    r = decode_anim(rec, nbones)
    if r and 5 + r[1] <= len(rec) + 0 and r[1] - 1 <= r[3] <= r[1]:
        return r
    return None


def parse_container(d, o, end):
    """EffectModelHeader at o: s32 numOffsets, s32 offsets[numOffsets]; offsets[0] = skeleton section, offsets[1] =
    script block, offsets[2..n-2] = animation records, offsets[n-1] = a TIM. Returns dict or None."""
    if o + 16 > end:
        return None
    n = u32(d, o)
    if not 3 <= n <= 256 or o + 4 + 4 * n > end:
        return None
    offs = struct.unpack_from("<%dI" % n, d, o + 4)
    if offs[0] != 4 + 4 * n:
        return None
    for a, b in zip(offs, offs[1:]):
        if b < a:
            return None
    if o + offs[-1] + 20 > end or not parse_tim(d, o + offs[-1], end, True):
        return None
    return {"n": n, "offs": offs}


def find_containers(ov):
    d = ov.d
    for o in range(0, ov.n - 16, 4):
        if ov.code_start <= o < ov.code_end:
            continue
        c = parse_container(d, o, ov.n)
        if not c:
            continue
        offs = c["offs"]
        n = c["n"]
        sk = o + offs[0]
        nb = u16(d, sk) + 1
        hdr_hi = u16(d, sk + 2)
        bones = []
        ok = True
        for i in range(nb):
            par, ln, mo = struct.unpack_from("<hhi", d, sk + 4 + 8 * i)
            bones.append((par, ln, mo))
            if not (0 <= par < nb):
                ok = False
        if not ok:
            continue
        if not ov.claim(o, o + 4 + 4 * n, "container.header", found=ov.how_found(o), numOffsets=n, bones=nb,
                        anims=n - 3, tim=offs[-1]):
            continue
        ov.claim(sk, sk + 4 + 8 * nb, "container.bones", bones=nb, hdr_hi=hdr_hi,
                 parents=[b[0] for b in bones], lengths=[b[1] for b in bones], flagged=sum(1 for b in bones if b[2] < 0))
        for i, (par, ln, mo) in enumerate(bones):
            if mo == 0:
                continue
            mo_abs = sk + 4 + (mo & 0x7FFFFFFF) - 4
            m = parse_mesh(d, mo_abs, o + offs[1])
            if m:
                ov.claim(mo_abs, mo_abs + m["len"], "container.mesh", bone=i, **mesh_detail(ov, mo_abs, m))
            else:
                ov.claims.append((mo_abs, mo_abs, "error", {"what": "bone mesh does not parse", "bone": i}))
        # script block: 8 offsets (relative to the block), then script bytes up to the first animation
        sb = o + offs[1]
        send = o + offs[2]
        so = struct.unpack_from("<8I", d, sb) if send - sb >= 32 else ()
        ov.claim(sb, send, "container.script", size=send - sb, offsets=list(so), body=d[sb + 32:send].hex())
        for k in range(2, n - 1):
            a, b = o + offs[k], o + offs[k + 1]
            if b - a < 5:
                ov.claim(a, b, "container.anim", index=k - 2, size=b - a, note="short record") if b > a else None
                continue
            r = anim_ok(d[a:b], nb)
            if r:
                ov.claim(a, b, "container.anim", index=k - 2, frames=r[0], size=r[1], key=r[2], used=r[3], rec=b - a)
            else:
                r = decode_anim(d[a:b], nb)
                ov.claim(a, b, "container.anim?", index=k - 2, rec=b - a, hdr=d[a:a + 5].hex(), used=r[3] if r else None)
        tm = parse_tim(d, o + offs[-1], ov.n, True)
        if tm["pix"][2] * tm["pix"][3] == 0:
            ov.claim(o + offs[-1], o + offs[-1] + tm["len"], "container.tim0", clut=tm.get("clut"), pix=tm["pix"])
        ov.containers.append((o, nb))


def find_animpacks(ov):
    """animation pack: u32 n, n ascending offsets (first = 4 + 4n), each to an animation record or a 4-byte
    placeholder. The bone count is not stored: it is the one count for which every record of the first half (and 1
    for the second half) decodes to its stated size."""
    d = ov.d
    for o in range(0, ov.n - 16, 4):
        if ov.owner[o]:
            continue
        n = u32(d, o)
        if not 2 <= n <= 64 or o + 4 + 4 * n > ov.n:
            continue
        offs = struct.unpack_from("<%dI" % n, d, o + 4)
        if offs[0] != 4 + 4 * n or any(b < a + 4 for a, b in zip(offs, offs[1:])) or o + offs[-1] + 4 > ov.n:
            continue
        recs = []
        for k in range(n):
            a = o + offs[k]
            if k + 1 < n:
                b = o + offs[k + 1]
            else:
                fr, size = struct.unpack_from("<HH", d, a)
                b = a + 4 if (fr, size) == (0x1A30, 0) else a + 5 + size + (-(5 + size) % 4)
            recs.append((a, b))
        if any(b > ov.n for a, b in recs):
            continue
        real = [k for k, (a, b) in enumerate(recs) if b - a > 4]
        if not real:
            continue
        best = None
        for nb in range(1, 64):
            good = [k for k in real if anim_ok(d[recs[k][0]:recs[k][1]], nb)]
            rest = [k for k in real if k not in good and anim_ok(d[recs[k][0]:recs[k][1]], 1)]
            if len(good) + len(rest) == len(real) and good:
                best = (nb, good, rest)
                break
        if not best:
            continue
        nb, good, rest = best
        if not ov.claim(o, o + 4 + 4 * n, "animpack.header", found=ov.how_found(o), count=n, bones=nb,
                        records=len(real), placeholders=n - len(real)):
            continue
        for k, (a, b) in enumerate(recs):
            if b - a <= 4:
                ov.claim(a, b, "animpack.placeholder", index=k, word=u32(d, a))
            else:
                r = anim_ok(d[a:b], nb if k in good else 1)
                ov.claim(a, b, "animpack.anim", index=k, bones=nb if k in good else 1, frames=r[0], size=r[1],
                         key=r[2], used=r[3], rec=b - a)


def find_loose_anims(ov):
    """animation records outside a container, at an address code builds: accepted when the stream decodes to the
    stated size with the bone count of one of the overlay's containers"""
    d = ov.d
    counts = sorted({nb for _, nb in ov.containers})
    for o in sorted(ov.code_refs):
        if o % 4 or ov.owner[o] or o + 8 > ov.n:
            continue
        fr, size, key = struct.unpack_from("<HHB", d, o)
        end = o + 5 + size + (-(5 + size) % 4)
        if not (0 < fr < 2000 and 8 < size and end <= ov.n) or not ov.free(o, end):
            continue
        for nb in counts:
            r = anim_ok(d[o:end], nb)
            if r:
                ov.claim(o, end, "anim", found="code", bones=nb, frames=r[0], size=r[1], key=r[2], used=r[3])
                break


# ---- sprite tables (upstream SpriteAnim) --------------------------------------------------------------------------

def parse_sprite(d, o, end):
    if o + 12 > end:
        return None
    n = struct.unpack_from("<i", d, o + 4)[0]
    if not 1 <= n <= 256:
        return None
    p = o + 8
    quads = 0
    tp = set()
    cl = set()
    for _ in range(n):
        if p + 4 > end:
            return None
        qc = s16(d, p + 2)
        if not 0 <= qc <= 64:
            return None
        p += 4
        for _ in range(qc):
            if p + 20 > end:
                return None
            flags, x, y, u, v, tpage, clut, w, uw, h, vh = struct.unpack_from("<IhhHHHHBBBB", d, p)
            if flags > 0xFFFF or tpage > 0x1FF or clut >= 0x8000 or (w == 0 and h == 0):
                return None
            tp.add(tpage)
            cl.add(clut)
            p += 20
        quads += qc
    if quads == 0:
        return None
    return {"len": p - o, "word0": u32(d, o), "frames": n, "quads": quads, "tpages": sorted(tp), "cluts": sorted(cl)}


def find_sprites(ov):
    cands = sorted(set(ov.code_refs) | set(ov.data_ptrs))
    for phase in (0, 1):
        offs = cands if phase == 0 else range(0, ov.n - 12, 4)
        for o in offs:
            if o % 4 or o >= ov.n or ov.owner[o]:
                continue
            s = parse_sprite(ov.d, o, ov.n)
            if not s or not ov.free(o, o + s["len"]):
                continue
            if phase == 1 and s["word0"] != 0x2023:
                continue
            ov.claim(o, o + s["len"], "sprite", found=ov.how_found(o), **{k: v for k, v in s.items() if k != "len"})


# ---- descriptors that point at the above ---------------------------------------------------------------------------

def find_descs(ov):
    d = ov.d
    starts = {}
    for a, b, kind, det in ov.claims:
        if kind in ("model", "sprite"):
            starts[a] = kind
    for tgt, kind in sorted(starts.items()):
        for po in ov.data_ptrs.get(tgt, ()):
            if kind == "model" and ov.free(po, po + 0x10):
                flags = u32(d, po + 4)
                if flags < 0x200:
                    ov.claim(po, po + 0x10, "desc.model", model=tgt, flags=flags, uvOffset=u16(d, po + 8),
                             color=s16(d, po + 10), tpage=s16(d, po + 12), clut=u16(d, po + 14))
            elif kind == "sprite" and ov.free(po, po + 0xC) and not (BASE <= u32(d, po + 4) < BASE + ov.n) \
                    and d[po + 7] in (0, 0x2C, 0x2D, 0x2E, 0x2F):
                ov.claim(po, po + 0xC, "desc.sprite", sprite=tgt, color=d[po + 4:po + 8].hex(),
                         frameIndex=u16(d, po + 8), clutBias=s16(d, po + 10))


def find_ptr_tables(ov):
    """runs of two or more consecutive words that each hold the address of the start of a claimed block or of a
    function-sized code address"""
    d = ov.d
    starts = {a: kind for a, b, kind, det in ov.claims if kind != "code"}
    o = 0
    lim = ov.n - 3
    while o < lim:
        if ov.owner[o] or o % 4:
            o += 4 - o % 4 if o % 4 else 4
            continue
        e = o
        kinds = collections.Counter()
        while e < lim and not ov.owner[e]:
            w = u32(d, e)
            if not (BASE <= w < BASE + ov.n):
                break
            fo = w - BASE
            if fo in starts:
                kinds[starts[fo]] += 1
            elif ov.code_start <= fo < ov.code_end and fo % 4 == 0:
                kinds["code"] += 1
            else:
                kinds["other"] += 1
            e += 4
        if e - o >= 4 and (e - o >= 8 or kinds["other"] == 0):
            ov.claim(o, e, "pointers", count=(e - o) // 4, to=dict(kinds))
            o = e
        else:
            o += 4


# ---- zero fill ------------------------------------------------------------------------------------------------------

def find_zero(ov, minrun=16):
    d, n = ov.d, ov.n
    o = 0
    while o < n:
        if ov.owner[o] or d[o]:
            o += 1
            continue
        e = o
        while e < n and not ov.owner[e] and not d[e]:
            e += 1
        if e - o >= minrun:
            refs = sorted(x for x in ov.code_refs if o <= x < e)
            kind = "zero"
            if e - o >= 0x18000:
                kind = "zero.buffers"
            ov.claim(o, e, kind, size=e - o, code_refs=len(refs), first_refs=[x - o for x in refs[:6]])
        o = e


def find_pad(ov):
    """zero bytes up to the next 4-byte boundary after a claimed block, and free zero runs under 16 bytes"""
    d, n = ov.d, ov.n
    o = 0
    while o < n:
        if ov.owner[o] or d[o]:
            o += 1
            continue
        e = o
        while e < n and not ov.owner[e] and not d[e]:
            e += 1
        left = o == 0 or ov.owner[o - 1]
        right = e == n or ov.owner[e]
        if left and right:
            ov.claim(o, e, "pad", size=e - o)
        o = e


def find_svec(ov):
    """shape only, no walked format: runs of 8-byte records (s16 x, y, z, 0) that start at an address code builds or
    a data pointer holds. Accepted when at least 8 records long and every record's fourth halfword is zero."""
    d = ov.d
    for o in sorted(set(ov.code_refs) | set(ov.data_ptrs)):
        if o % 4 or o >= ov.n or ov.owner[o]:
            continue
        e = o
        nz = 0
        ny = 0
        while e + 8 <= ov.n and not any(ov.owner[e:e + 8]) and d[e + 6] == 0 and d[e + 7] == 0:
            if e > o and (e in ov.code_refs or e in ov.data_ptrs) and e - o >= 64:
                break
            if d[e:e + 6] != b"\0" * 6:
                nz += 1
            if d[e + 2] or d[e + 3]:
                ny += 1
            e += 8
        n = (e - o) // 8
        if n >= 16 and nz * 10 >= n * 7 and ny * 10 >= n * 3:
            ov.claim(o, e, "svec", found=ov.how_found(o), records=n)


FINDERS = (find_tims, find_containers, find_animpacks, find_loose_anims, find_models, find_sprites, find_descs,
           find_ptr_tables, find_svec, find_zero, find_pad)

# what each kind counts as in the coverage figure
TIER = {"code": "code", "tim": "format", "container.header": "format", "container.bones": "format",
        "container.mesh": "format", "container.script": "format", "container.anim": "format",
        "container.anim?": "unplaced", "container.tim0": "format", "animpack.header": "format",
        "animpack.anim": "format", "animpack.placeholder": "format", "anim": "format", "model": "format",
        "sprite": "format", "desc.model": "format", "desc.sprite": "format", "pointers": "format",
        "zero.buffers": "zero", "zero": "zero", "pad": "zero", "svec": "shape", "error": "unplaced"}


def analyse(name, data, code_start, code_end):
    ov = Overlay(name, data, code_start, code_end)
    if code_end > code_start:
        ov.claim(code_start, min(code_end, ov.n), "code")
    scan_refs(ov)
    for f in FINDERS:
        f(ov)
    return ov


def unknown_ranges(ov):
    """free ranges: (start, end, class). class 'private' = code builds an address inside the range (variables and
    tables of the overlay's own code, no shared format); 'unplaced' = nothing addresses it"""
    out = []
    o = 0
    refs = sorted(ov.code_refs)
    import bisect
    while o < ov.n:
        if ov.owner[o]:
            o += 1
            continue
        e = o
        while e < ov.n and not ov.owner[e]:
            e += 1
        k = bisect.bisect_left(refs, o)
        nref = bisect.bisect_left(refs, e) - k
        out.append((o, e, "private" if nref else "unplaced", nref))
        o = e
    return out


def consistency(ovs):
    """cross-checks between formats inside one overlay; returns a Counter"""
    c = collections.Counter()
    for ov in ovs:
        tims = [det for a, e, k, det in ov.claims if k == "tim"]
        cluts = [det["clut"] for det in tims if "clut" in det]
        pixs = [det["pix"] for det in tims]
        nanim = {}
        for a, e, k, det in ov.claims:
            if k == "sprite":
                c["sprite tables"] += 1
                ok_c = all(any(x <= (cl & 0x3F) * 16 < x + w and y <= cl >> 6 < y + h for x, y, w, h in cluts)
                           for cl in det["cluts"])
                ok_p = all(any(x < (tp & 15) * 64 + 256 and (tp & 15) * 64 < x + w * (4 if True else 1)
                               and y < ((tp >> 4) & 1) * 256 + 256 and ((tp >> 4) & 1) * 256 < y + h
                               for x, y, w, h in pixs) for tp in det["tpages"])
                c["sprite tables whose every clut lies in a clut rectangle of a TIM of the same overlay"] += ok_c
                c["sprite tables whose every tpage overlaps a pixel rectangle of a TIM of the same overlay"] += ok_p
            elif k == "container.header":
                nanim[a] = det["anims"]
                last = det["anims"]
            elif k == "container.script":
                body = bytes.fromhex(det["body"])[24:]
                c["container scripts"] += 1
                # bytes below 0x8E are animation indices (reader: the interpreter's opcode test); operands of
                # opcodes are not walked here, so only scripts made of indices, C9, C1, F1 and padding are checked
                if all(b < 0x8E or b in (0xC9, 0xC1, 0xF1) for b in body):
                    c["scripts made only of animation indices and C9 / C1 / F1"] += 1
                    c["... whose every index is below the container's animation count"] += all(
                        b < last for b in body if b < 0x8E)
    return c


def read_table(path):
    rows = {}
    with open(path, newline="") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            rows[r["file"].upper()] = r
    return rows


# ---- the PC release's magic.lgp, unpacked: names and contents ------------------------------------------------------

PC_SCALES = (1, 25, 200, 100, 50, 500, 75, 400, 250, 28, 1000)


def pc_index(pc_dir):
    files = []
    for root, _, names in os.walk(pc_dir):
        for nm in names:
            p = os.path.join(root, nm)
            files.append((os.path.relpath(p, pc_dir).replace(os.sep, "/"), p))
    return sorted(files)


def pc_p_vertices(b):
    """PC P-file: word 1 at 0, vertex count at 0x0C, float vertices from 0x80"""
    if len(b) < 0x80 or u32(b, 0) != 1:
        return None
    nv = u32(b, 0x0C)
    if nv == 0 or 0x80 + 12 * nv > len(b):
        return None
    return set(struct.unpack_from("<3f", b, 0x80 + 12 * i) for i in range(nv))


def pc_anims(b):
    """PC animation file: u32 count, then per animation u32 bones, u32 frames, u32 size and `size` bytes that are
    the PS1 record (u16 frames, u16 size, u8 key, bit stream). Records with size < 11 carry no stream."""
    if len(b) < 4:
        return None
    n = u32(b, 0)
    out = []
    p = 4
    for _ in range(n):
        if p + 12 > len(b):
            return None
        bones, frames, size = struct.unpack_from("<3I", b, p)
        p += 12
        if p + size > len(b):
            return None
        out.append((bones, frames, size, b[p:p + size]))
        p += size
    return out


def pc_cross(ovs, pc_dir, outdir):
    files = pc_index(pc_dir)
    sprites = collections.defaultdict(list)      # bytes -> [(overlay, offset)]
    sprites_nt = collections.defaultdict(list)   # bytes with the tpage halfwords zeroed
    scripts = collections.defaultdict(list)
    anims = collections.defaultdict(list)
    vert_index = collections.defaultdict(set)    # vertex -> mesh ids
    meshes = []
    bonesets = []

    def no_tpage(b):
        b = bytearray(b)
        p = 8
        while p + 4 <= len(b):
            qc = s16(b, p + 2)
            p += 4
            for _ in range(max(qc, 0)):
                if p + 20 > len(b):
                    break
                b[p + 12:p + 14] = b"\0\0"
                p += 20
        return bytes(b)

    for ov in ovs:
        d = ov.d
        for a, e, kind, det in ov.claims:
            if kind == "sprite":
                sprites[d[a:e]].append((ov.name, a))
                sprites_nt[no_tpage(d[a:e])].append((ov.name, a))
            elif kind == "container.script":
                scripts[d[a:e]].append((ov.name, a))
            elif kind in ("container.anim", "animpack.anim", "anim"):
                anims[d[a:a + 5 + det["size"]]].append((ov.name, a))
            elif kind in ("model", "container.mesh"):
                vs = set(struct.unpack_from("<3h", d, a + 4 + 8 * i) for i in range(det["nverts"]))
                mid = len(meshes)
                meshes.append((ov.name, a, kind, vs))
                for v in vs:
                    vert_index[v].add(mid)
            elif kind == "container.bones":
                bonesets.append((ov.name, a, det["lengths"][1:], det["parents"][1:]))
    rows = []
    stat = collections.Counter()
    for rel, path in files:
        ext = rel.rsplit(".", 1)[-1].lower() if "." in rel else ""
        b = open(path, "rb").read()
        hit = []
        how = ""
        if ext == "s":
            stat["s files"] += 1
            if b in sprites:
                hit, how = sprites[b], "identical"
            elif no_tpage(b) in sprites_nt:
                hit, how = sprites_nt[no_tpage(b)], "identical but tpage"
        elif ext == "b":
            stat["b files"] += 1
            if b in scripts:
                hit, how = scripts[b], "identical"
        elif ext[:1] == "a" and ext[1:].isdigit():
            stat["aNN files"] += 1
            recs = pc_anims(b)
            if recs:
                real = [r for r in recs if r[2] >= 11]
                got = [anims.get(r[3][:5 + struct.unpack_from("<H", r[3], 2)[0]]) for r in real]
                n_ok = sum(1 for g in got if g)
                stat["aNN records"] += len(real)
                stat["aNN records identical"] += n_ok
                if n_ok:
                    c = collections.Counter(x[0] for g in got if g for x in g)
                    hit = [(c.most_common(1)[0][0], -1)]
                    how = "%d of %d records identical" % (n_ok, len(real))
        elif ext == "d":
            stat["d files"] += 1
            if len(b) >= 52:
                nb = u32(b, 0x0C)
                if 52 + 12 * nb <= len(b):
                    lens = [struct.unpack_from("<ifI", b, 52 + 12 * i) for i in range(nb)]
                    for name, a, pl, pp in bonesets:
                        if len(pl) == nb and all(int(x[1]) == y for x, y in zip(lens, pl)):
                            hit.append((name, a))
                            how = "bone count and all lengths equal"
        elif ext == "p" or (ext[:1] == "p" and ext[1:].isdigit()):
            stat["p files"] += 1
            vs = pc_p_vertices(b)
            if vs and len(vs) >= 8:
                for sc in PC_SCALES:
                    cand = None
                    for v in vs:
                        m = vert_index.get(tuple(int(sc * x) for x in v))
                        if not m:
                            cand = None
                            break
                        cand = set(m) if cand is None else cand & m
                        if not cand:
                            break
                    if cand:
                        hit = [(meshes[m][0], meshes[m][1]) for m in sorted(cand)]
                        how = "every vertex = trunc(%d x) of the block's" % sc
                        break
        else:
            continue
        if hit:
            stat[("matched", ext if ext in ("s", "b", "d", "p") else ext[0] + "NN")] += 1
        rows.append((rel, ext, len(b), how, ";".join("%s+0x%X" % (n, a) if a >= 0 else n for n, a in hit[:6]),
                     len(hit)))
    with open(os.path.join(outdir, "PC-ASSETS.tsv"), "w", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["pc_file", "kind", "bytes", "match", "ps1_blocks", "n_blocks"])
        w.writerows(rows)
    # overlay -> named assets
    byov = collections.defaultdict(lambda: collections.defaultdict(set))
    for rel, ext, n, how, blocks, nh in rows:
        for blk in blocks.split(";"):
            if blk:
                nm, _, off = blk.partition("+")
                byov[nm][off].add(rel)
    with open(os.path.join(outdir, "OVERLAY-ASSETS.tsv"), "w", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["overlay", "offset", "kind", "bytes", "pc_names"])
        for ov in ovs:
            for a, e, kind, det in sorted(ov.claims):
                key = "0x%X" % a
                names = set(byov[ov.name].get(key, ()))
                if kind == "container.anim":
                    names |= byov[ov.name].get("", set())
                if names:
                    w.writerow([ov.name, key, kind, e - a, " ".join(sorted(names)[:8])])
    return stat


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("magic")
    ap.add_argument("--pc", help="folder with the unpacked PC magic.lgp")
    ap.add_argument("--table", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "overlays.tsv"))
    ap.add_argument("--out", default=".")
    ap.add_argument("--only", help="comma list of overlay names")
    ap.add_argument("--dump", action="store_true", help="print every claim of the --only overlays")
    a = ap.parse_args()
    table = read_table(a.table)
    only = set(x.lower() for x in a.only.split(",")) if a.only else None
    os.makedirs(a.out, exist_ok=True)
    kinds = collections.Counter()
    counts = collections.Counter()
    tiers = collections.Counter()
    ovs = []
    cov_rows = []
    unk_rows = []
    blk_rows = []
    for fn in sorted(table):
        r = table[fn]
        if only and r["overlay"].lower() not in only:
            continue
        data = open(os.path.join(a.magic, fn), "rb").read()
        if hashlib.sha1(data).hexdigest() != r["sha1"]:
            print("sha1 mismatch: %s" % fn, file=sys.stderr)
        ov = analyse(r["overlay"], data, int(r["code_start"]), int(r["code_end"]))
        ovs.append(ov)
        c = collections.Counter()
        t = collections.Counter()
        for s, e, kind, det in ov.claims:
            c[kind] += e - s
            counts[kind] += 1
            t[TIER[kind]] += e - s
            if kind != "code":
                blk_rows.append([ov.name, "0x%X" % s, e - s, kind, det.get("found", ""),
                                 json.dumps({k: v for k, v in det.items() if k not in ("found", "body")},
                                            separators=(",", ":"))[:300]])
        unk = unknown_ranges(ov)
        for s, e, cls, nref in unk:
            c[cls] += e - s
            counts[cls] += 1
            t[cls] += e - s
            unk_rows.append([ov.name, "0x%X" % s, "0x%X" % e, e - s, cls, nref])
        kinds.update(c)
        tiers.update(t)
        cov_rows.append([ov.name, ov.n] + [t[k] for k in ("code", "format", "zero", "shape", "private", "unplaced")])
        if a.dump:
            for s, e, kind, det in sorted(ov.claims, key=lambda x: (x[0], x[1])):
                print("%06X %06X %-20s %s" % (s, e, kind, json.dumps(det, default=str)[:230]))
            for s, e, cls, nref in unk:
                print("%06X %06X %-20s %d bytes, %d code refs  %s" % (s, e, cls.upper(), e - s, nref, data[s:s + 24].hex(" ")))
    total = sum(ov.n for ov in ovs)
    print("overlays %d  bytes %d" % (len(ovs), total))
    print("\nby kind (blocks, bytes, share of all bytes)")
    for k, v in kinds.most_common():
        print("  %-22s %6d %10d  %6.2f %%" % (k, counts[k], v, 100.0 * v / total))
    data_total = total - tiers["code"]
    nonzero = data_total - tiers["zero"]
    print("\ncoverage")
    for k, label in (("code", "code (from the overlay table)"), ("format", "data walked by a format of the model"),
                     ("zero", "zero fill"), ("shape", "typed by shape only (vector arrays)"),
                     ("private", "not placed, but code addresses it (the overlay's own variables and tables)"),
                     ("unplaced", "not placed, nothing addresses it")):
        print("  %-78s %10d  %6.2f %% of all, %6.2f %% of data" % (label, tiers[k], 100.0 * tiers[k] / total,
              100.0 * tiers[k] / data_total if k != "code" else 0))
    print("  data bytes %d; non-zero-fill data %d; of that walked by a format: %.2f %%; with shape-only: %.2f %%"
          % (data_total, nonzero, 100.0 * tiers["format"] / nonzero, 100.0 * (tiers["format"] + tiers["shape"]) / nonzero))
    print("  all bytes placed (code + format + zero): %.2f %%"
          % (100.0 * (tiers["code"] + tiers["format"] + tiers["zero"]) / total))
    summary = {"overlays": len(ovs), "bytes": total, "by_kind_bytes": dict(kinds), "by_kind_blocks": dict(counts),
               "tiers": dict(tiers)}
    if not only:
        for name, hdr, rows in (("COVERAGE.tsv", ["overlay", "bytes", "code", "format", "zero", "shape", "private", "unplaced"], cov_rows),
                                ("UNPLACED.tsv", ["overlay", "start", "end", "bytes", "class", "code_refs"], unk_rows),
                                ("BLOCKS.tsv", ["overlay", "offset", "bytes", "kind", "found_by", "fields"], blk_rows)):
            with open(os.path.join(a.out, name), "w", newline="") as f:
                w = csv.writer(f, delimiter="\t", lineterminator="\n")
                w.writerow(hdr)
                w.writerows(rows)
    chk = consistency(ovs)
    print("\nconsistency between formats")
    for k, v in chk.items():
        print("  %-86s %d" % (k, v))
    summary["consistency"] = dict(chk)
    if a.pc:
        stat = pc_cross(ovs, a.pc, a.out)
        print("\nPC archive against the claimed blocks")
        for k, v in sorted(stat.items(), key=str):
            print("  %-36s %d" % (k if isinstance(k, str) else "%s: %s" % k, v))
        summary["pc"] = {(k if isinstance(k, str) else "%s %s" % k): v for k, v in stat.items()}
    if not only:
        with open(os.path.join(a.out, "SUMMARY.json"), "w") as f:
            json.dump(summary, f, indent=1, sort_keys=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
