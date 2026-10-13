#!/usr/bin/env python3
"""magic_shared.py : measurements behind MAGIC-OVERLAYS-SHARED.md. Every number in that document is printed or written
by this script. Python 3 standard library only; no other tool, no other file of any repository is needed.

  magic_shared.py --magic DIR [--table FILE] [--battle FILE] [--symbols DIR] [--src DIR] [--out DIR]

  --magic DIR     folder holding the overlay files (MAGIC/*.BIN of the US disc; the 287 files of the table)
  --table FILE    MAGIC-OVERLAYS-OVERLAYS.tsv (attached): per overlay the file, load address, sha1 of the file and where
                  its code starts and ends. Default: the file next to this script. The script checks every file's sha1.
  --battle FILE   BATTLE.X.dec of the disc, for the table of overlay entry addresses (skipped when absent);
                  --battle-vram is its load address (default 0x800A0000)
  --symbols DIR   optional: a checkout whose config/symbols.*.txt (`name = 0xADDR;`) name the main/battle addresses that
                  overlay code calls and reads; without it addresses are printed
  --src DIR       optional: a tree with src/magic/*.c (`//! PSYQ=` header lines, INCLUDE_ASM lines); only the compiler
                  and the function-count cross-check use it, and they are skipped without it
  --out DIR       where MAGIC-OVERLAYS-FAMILIES.tsv, MAGIC-OVERLAYS-NUMBERS.json (and a refreshed OVERLAYS table) go
  --make-table YAML   write the overlay table from a config/us.yaml (needs PyYAML) and stop

Method:
  functions   starts: the first word of each code range, every `jal` target inside it, and the word after the delay slot
              of a `jr $ra` that no earlier forward branch jumps past
  skeleton    each instruction with immediates, jump targets and branch offsets masked (opcode, registers, shift
              amounts and function field kept): "the same instructions"
  clone       skeleton with only ADDRESS-valued immediates masked (a `lui` of 0x8000-0x8020 and the offsets of the loads,
              stores, addiu and ori that use that register, and jal/j targets): "the same code, other data"
"""
import argparse
import collections
import hashlib
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TABLE = os.path.join(HERE, "MAGIC-OVERLAYS-OVERLAYS.tsv")
MIN_FAMILY_INS = 10      # a family needs at least this many instructions (below that: stubs, listed separately)
TOP_FAMILIES = 12        # rows of the family table the document prints
CODE_TYPES = {"c", "asm", "hasm"}
ADDR_LO, ADDR_HI = 0x8000, 0x8020   # `lui` immediates that are RAM addresses (kernel RAM, overlays, scratch)


def words(b):
    return struct.unpack("<%dI" % (len(b) // 4), b[:len(b) // 4 * 4])


def op(w):
    return w >> 26


def is_jr_ra(w):
    return w == 0x03E00008


def branch_target(i, w):
    o = op(w)
    rt = (w >> 16) & 31
    if o in (4, 5, 6, 7) or (o == 1 and rt in (0, 1, 16, 17)):
        off = w & 0xFFFF
        if off & 0x8000:
            off -= 0x10000
        return i + 1 + off
    return None


def split_functions(ws, base):
    """function start indices (word indices) in a code run of words ws loaded at `base` (word 0 = vram base)"""
    n = len(ws)
    starts = {0}
    for i, w in enumerate(ws):
        if op(w) == 3:   # jal
            t = ((w & 0x3FFFFFF) << 2) - base
            if 0 <= t < n * 4 and t % 4 == 0:
                starts.add(t // 4)
    far = 0
    for i, w in enumerate(ws):
        t = branch_target(i, w)
        if t is not None and t > far:
            far = t
        if is_jr_ra(w) and i + 2 <= n - 1 and far <= i + 1:
            starts.add(i + 2)
    return sorted(s for s in starts if s < n)


def mask(w, kind):
    """kind 'skel' masks all immediates; 'clone' only address-valued ones (see module doc). Returns a word."""
    o = op(w)
    if o in (2, 3):
        return w & 0xFC000000
    if o == 0 or o == 0x12:   # R-type, COP2 (GTE ops keep their full word)
        return w
    return w & 0xFFFF0000


def clone_key(seq):
    """masked words for the clone level: immediates survive unless address-valued"""
    out = []
    addr_regs = set()
    for w in seq:
        o = op(w)
        rs, rt = (w >> 21) & 31, (w >> 16) & 31
        imm = w & 0xFFFF
        if o == 15:   # lui
            if ADDR_LO <= imm < ADDR_HI:
                addr_regs.add(rt)
                out.append(w & 0xFFFF0000)
            else:
                addr_regs.discard(rt)
                out.append(w)
        elif o in (2, 3):
            out.append(w & 0xFC000000)
        elif o in (8, 9, 12, 13, 14, 32, 33, 34, 35, 36, 37, 38, 40, 41, 42, 43, 46, 49, 57):
            # addi/addiu/andi/ori/xori, loads, stores
            if rs in addr_regs:
                out.append(w & 0xFFFF0000)
                if o in (8, 9, 13, 14):    # the result is an address too (or its low half merged in)
                    addr_regs.add(rt)
            else:
                out.append(w)
                if rt in addr_regs and o in (8, 9, 12, 13, 14, 32, 33, 34, 35, 36, 37, 38):
                    addr_regs.discard(rt)
        else:
            out.append(w)
            if o == 0:
                rd = (w >> 11) & 31
                fn = w & 63
                if fn in (0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x2A, 0x2B, 0, 2, 3, 4, 6, 7):
                    addr_regs.discard(rd)
    return out


def read_table(path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        head = fh.readline().rstrip("\n").split("\t")
        for line in fh:
            c = line.rstrip("\n").split("\t")
            if len(c) == len(head):
                rows.append(dict(zip(head, c)))
    return sorted(rows, key=lambda r: r["overlay"])   # one order whatever the table's, so ties come out the same


def make_table(yaml_path, magic_dir, out_path):
    """overlay table from a config/us.yaml: file, load address, sha1, code range (first and last code segment), bss"""
    import yaml
    y = yaml.safe_load(open(yaml_path, encoding="utf-8"))
    cols = ["overlay", "file", "vram", "sha1", "code_start", "code_end", "bss", "imports"]
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\t".join(cols) + "\n")
        for ov in y["overlays"]:
            if ov.get("base_path") != "magic":
                continue
            fn = os.path.basename(ov["disk_path"])
            size = os.path.getsize(os.path.join(magic_dir, fn))
            segs = [s for s in ov["segments"] if len(s) >= 2]
            code = [(sg[0], segs[i + 1][0] if i + 1 < len(segs) else size) for i, sg in enumerate(segs)
                    if sg[1] in ("c", "asm", "hasm")]
            fh.write("\t".join([ov["name"], fn, "0x%08X" % ov["vram_start"], ov["sha1"], str(code[0][0]), str(code[-1][1]),
                                str(ov.get("bss_size", 0)), "+".join(ov.get("imports", []))]) + "\n")


def load_overlays(magic_dir, table):
    res = []
    for r in table:
        data = open(os.path.join(magic_dir, r["file"]), "rb").read()
        cs, ce = int(r["code_start"]), min(int(r["code_end"]), len(data))
        segs = [x for x in ((0, cs, "data"), (cs, ce, "code"), (ce, len(data), "data")) if x[1] > x[0]]
        res.append({"name": r["overlay"], "file": r["file"], "data": data,
                    "sha_ok": hashlib.sha1(data).hexdigest() == r["sha1"], "vram": int(r["vram"], 0),
                    "bss": int(r.get("bss", 0) or 0), "segs": segs, "imports": [x for x in r.get("imports", "").split("+") if x]})
    return res


def measure(magic_dir, table):
    ovs = load_overlays(magic_dir, table)
    funcs = []   # dict rows
    ovrows = []
    for ov in ovs:
        code = bytearray()
        code_regions = []
        for s, e, k in ov["segs"]:
            if k == "code":
                code_regions.append((s, e))
        code_bytes = sum(e - s for s, e in code_regions)
        data_bytes = sum(e - s for s, e, k in ov["segs"] if k == "data")
        nf = 0
        for s, e in code_regions:
            ws = words(ov["data"][s:e])
            base = ov["vram"] + s
            st = split_functions(ws, base)
            for j, a in enumerate(st):
                z = st[j + 1] if j + 1 < len(st) else len(ws)
                seq = list(ws[a:z])
                funcs.append({"overlay": ov["name"], "addr": base + a * 4, "off": s + a * 4, "n": len(seq),
                              "skel": hashlib.sha1(b"".join(struct.pack("<I", mask(w, "skel")) for w in seq)).hexdigest()[:12],
                              "clone": hashlib.sha1(b"".join(struct.pack("<I", w) for w in clone_key(seq))).hexdigest()[:12],
                              "seq": seq, "first_off": s + a * 4})
                nf += 1
        ovrows.append({"overlay": ov["name"], "file": ov["file"], "bytes": len(ov["data"]), "code": code_bytes,
                       "data": data_bytes, "bss": ov["bss"], "functions": nf, "code_start": min(s for s, e, k in ov["segs"] if k == "code"),
                       "code_end": max(e for s, e, k in ov["segs"] if k == "code"), "sha1": hashlib.sha1(ov["data"]).hexdigest(), "vram": "0x%08X" % ov["vram"],
                       "sha_ok": ov["sha_ok"], "imports": "+".join(ov["imports"])})
    return ovs, funcs, ovrows


# ---- analysis -------------------------------------------------------------------------------------------------

def upstream_names(updir):
    """address -> name from the symbol files of an upstream checkout (names upstream already has; not ours)"""
    import glob
    import re
    out = {}
    for p in sorted(glob.glob(os.path.join(updir, "config", "symbols.*.txt")) + glob.glob(os.path.join(updir, "config", "*.txt"))):
        if "magic-" in os.path.basename(p):
            continue
        for line in open(p, encoding="utf-8", errors="replace"):
            m = re.match(r"^\s*(\w+)\s*=\s*0x([0-9A-Fa-f]{8})\s*;", line)
            if m:
                a = int(m.group(2), 16)
                nm = m.group(1)
                if a not in out or (out[a].startswith(("func_", "D_")) and not nm.startswith(("func_", "D_"))):
                    out[a] = nm
    return out


def refs(seq):
    """addresses formed by lui+lo pairs, and jal targets: ([data/code address refs], [jal targets])"""
    hi = {}
    addrs = []
    jals = []
    for w in seq:
        o = op(w)
        rs, rt, imm = (w >> 21) & 31, (w >> 16) & 31, w & 0xFFFF
        if o == 15:
            hi[rt] = imm << 16
        elif o == 3:
            jals.append(0x80000000 | ((w & 0x3FFFFFF) << 2))
        elif o in (8, 9, 13, 14, 32, 33, 34, 35, 36, 37, 38, 40, 41, 42, 43, 46, 49, 57) and rs in hi:
            simm = imm - 0x10000 if imm & 0x8000 else imm
            a = (hi[rs] + (imm if o in (13, 14) else simm)) & 0xFFFFFFFF
            if 0x80000000 <= a < 0x80200000:
                addrs.append(a)
            if o in (8, 9, 13, 14) and rt != rs:
                hi[rt] = hi[rs]
        else:
            if o not in (43, 40, 41, 42, 46, 57):   # stores do not define rt
                hi.pop(rt, None) if o not in (4, 5, 6, 7, 1) else None
    return addrs, jals


def classify_diff(ws):
    """ws: the raw word at one position in every member. Returns the kind of variation."""
    o = op(ws[0])
    if o in (2, 3):
        return "jump"
    if o == 15:
        return "addr-hi" if all(ADDR_LO <= (w & 0xFFFF) < ADDR_HI for w in ws) else "const"
    if o in (4, 5, 6, 7, 1):
        return "branch"
    return "imm"


def families(funcs, level):
    g = collections.defaultdict(list)
    for f in funcs:
        g[f[level]].append(f)
    fams = []
    for k, v in g.items():
        if len({x["overlay"] for x in v}) >= 2:
            fams.append(v)
    fams.sort(key=lambda v: (-len(v) * v[0]["n"], v[0]["skel"]))
    return fams


def vary(members):
    """positions where raw words differ among members, by kind"""
    n = members[0]["n"]
    kinds = collections.Counter()
    for i in range(n):
        col = [m["seq"][i] for m in members]
        if len(set(col)) > 1:
            kinds[classify_diff(col)] += 1
    return kinds


def near_families(funcs, exact_keys, min_ins=20, min_ratio=0.85):
    """functions not in an exact (skeleton) family, grouped when their masked word sequences are >= min_ratio alike.
    Candidates by shared 4-gram shingles; confirmed with difflib. Returns list of clusters (lists of funcs)."""
    import difflib
    cand = [f for f in funcs if f["skel"] not in exact_keys and f["n"] >= min_ins]
    for f in cand:
        f["_m"] = [mask(w, "skel") for w in f["seq"]]
    idx = collections.defaultdict(list)
    sh = []
    for i, f in enumerate(cand):
        s = {tuple(f["_m"][j:j + 4]) for j in range(0, len(f["_m"]) - 3)}
        sh.append(s)
        for t in s:
            idx[t].append(i)
    parent = list(range(len(cand)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for i, f in enumerate(cand):
        cnt = collections.Counter()
        for t in sh[i]:
            lst = idx[t]
            if len(lst) > 60:
                continue
            for j in lst:
                if j > i and cand[j]["overlay"] != f["overlay"]:
                    cnt[j] += 1
        for j, c in cnt.items():
            if c < 0.5 * min(len(sh[i]), len(sh[j])):
                continue
            a, b = f["_m"], cand[j]["_m"]
            if min(len(a), len(b)) / max(len(a), len(b)) < min_ratio:
                continue
            r = difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()
            if r >= min_ratio:
                parent[find(i)] = find(j)
    cl = collections.defaultdict(list)
    for i in range(len(cand)):
        cl[find(i)].append(cand[i])
    return [v for v in cl.values() if len({x["overlay"] for x in v}) >= 2]


def tim_scan(d):
    """(count, bytes) of PSX TIM images found by header and block sizes; found = start offsets"""
    out = []
    i = 0
    n = len(d)
    while i + 20 <= n:
        if d[i:i + 4] == b"\x10\x00\x00\x00":
            flag = struct.unpack_from("<I", d, i + 4)[0]
            if flag in (0, 1, 2, 3, 8, 9, 10, 11):
                j = i + 8
                ok = True
                if flag & 8:
                    bnum = struct.unpack_from("<I", d, j)[0]
                    if bnum < 12 or bnum > 0x2000 or j + bnum > n:
                        ok = False
                    else:
                        j += bnum
                if ok and j + 12 <= n:
                    bnum2 = struct.unpack_from("<I", d, j)[0]
                    w, h = struct.unpack_from("<HH", d, j + 8)
                    if 12 <= bnum2 <= 0x40000 and j + bnum2 <= n and 0 < w <= 1024 and 0 < h <= 512:
                        out.append((i, j + bnum2 - i, d[i:j + bnum2]))
                        i = j + bnum2
                        continue
        i += 4
    return out


def src_headers(tree):
    """per-file compiler line and number of C-defined functions of src/magic/*.c in `tree`"""
    import glob
    import re
    res = {}
    for p in sorted(glob.glob(os.path.join(tree, "src", "magic", "*.c"))):
        t = open(p, encoding="utf-8", errors="replace").read()
        first = t.split("\n", 1)[0]
        hdr = first[4:].strip() if first.startswith("//! ") else ""
        asm = len(re.findall(r"^INCLUDE_ASM\(", t, re.M))
        defd = len(re.findall(r"^[A-Za-z_][\w \t\*]*\b\w+\s*\([^;{]*\)\s*\{", t, re.M))
        res[os.path.splitext(os.path.basename(p))[0]] = (hdr, defd, asm)
    return res


def battle_table(path, base):
    """the table of overlay entry addresses in the original battle executable: the longest run of words that point
    into the first 8 KB of the overlay range (0x801B0000..0x801B2000) or into the battle code itself"""
    if not path or not os.path.exists(path):
        return {}
    d = open(path, "rb").read()
    w = struct.unpack("<%dI" % (len(d) // 4), d[:len(d) // 4 * 4])
    best = None
    i = 0
    while i < len(w):
        if 0x801B0000 <= w[i] < 0x801B2000:
            j = i
            while j < len(w) and (0x801B0000 <= w[j] < 0x801B2000 or base <= w[j] < base + len(d)):
                j += 1
            if j - i >= 8 and (best is None or j - i > best[1]):
                best = (i, j - i)
            i = j
        else:
            i += 1
    if not best:
        return {}
    i, n = best
    ents = [x for x in w[i:i + n] if 0x801B0000 <= x < 0x801B2000]
    c = collections.Counter(ents)
    return {"file_offset": "0x%X" % (i * 4), "vram": "0x%08X" % (base + i * 4), "words": n, "overlay_entries": len(ents),
            "distinct_entry_addresses": len(c), "most_common": [("0x%08X" % k, v) for k, v in c.most_common(6)]}



# ---- what the non-image, non-zero data is ---------------------------------------------------------------------

def model_len(d, o, end):
    """length of a battle model block at o (BattleDrawModel layout) or 0"""
    if o + 16 > end: return 0
    f = struct.unpack_from('<I', d, o)[0]
    if f < 8 or f % 8 or o + 4 + f + 16 > end or f > 0x10000: return 0
    nv = f // 8
    # vertex pads must be zero (SVECTOR) in the first/last vertices
    for k in (0, 1, nv - 1):
        if struct.unpack_from('<h', d, o + 4 + k * 8 + 6)[0] != 0: return 0
    p = o + 4 + f
    tot = 0
    for stride, wide in ((0x10, False), (0x14, True), (0x14, False), (0x18, True)):
        if p + 4 > end: return 0
        n = struct.unpack_from('<I' if wide else '<H', d, p)[0]
        if n > 4000: return 0
        # indices are byte offsets into the vertex array: multiples of 8, < f
        for k in range(min(n, 3)):
            q = p + 4 + k * stride
            if q + 6 > end: return 0
            for j in range(2):
                v = struct.unpack_from('<h', d, q + j * 2)[0]
                if v < 0 or v >= f or v % 8: return 0
        p += 4 + n * stride
        tot += n
    if p > end or tot == 0: return 0
    return p - o

def sprite_len(d, o, end):
    """length of a SpriteAnim at o (upstream battle.h: SpriteAnim/SpriteFrame/SpriteQuad) or 0"""
    if o + 8 > end: return 0
    n = struct.unpack_from('<i', d, o + 4)[0]
    if not 1 <= n <= 256: return 0
    p = o + 8
    for i in range(n):
        if p + 4 > end: return 0
        qc = struct.unpack_from('<h', d, p + 2)[0]
        if not 0 <= qc <= 64: return 0
        p += 4
        for k in range(qc):
            if p + 20 > end: return 0
            flags, x, y, u, v, tp, clut, w, uw, h, vh = struct.unpack_from('<IhhHHHHBBBB', d, p)
            if flags > 0xFFFF or tp > 0x1FF or not (0x4000 <= clut < 0x8000): return 0
            p += 20
    return p - o


def svector_like(seg):
    """share of 8-byte records (s16 x, y, z, pad) whose pad is zero and whose x, y, z are not all zero"""
    n = len(seg) // 8
    if n < 4:
        return 0.0
    ok = 0
    for k in range(n):
        x, y, z, pad = struct.unpack_from("<hhhh", seg, k * 8)
        if pad == 0 and (x or y or z):
            ok += 1
    return ok / n


def data_kinds(ovs, funcs, names):
    """classify the non-zero bytes of the data that are neither TIM images nor in a zero run: returns (rows, details)"""
    by_ov = {ov["name"]: ov for ov in ovs}
    # addresses (offsets in the file) that code builds with lui/lo pairs, and the routine called next
    code_refs = collections.defaultdict(lambda: collections.defaultdict(set))
    for f in funcs:
        seq = f["seq"]
        hi = {}
        for i, w in enumerate(seq):
            o = op(w)
            rs, rt, imm = (w >> 21) & 31, (w >> 16) & 31, w & 0xFFFF
            if o == 15:
                hi[rt] = imm << 16
            elif o in (8, 9, 13) and rs in hi:
                a = (hi[rs] + (imm if o == 13 else (imm - 0x10000 if imm & 0x8000 else imm))) & 0xFFFFFFFF
                if 0x801B0000 <= a < 0x80200000:
                    cal = "none"
                    for w2 in seq[i + 1:i + 15]:
                        if op(w2) == 3:
                            t = 0x80000000 | ((w2 & 0x3FFFFFF) << 2)
                            cal = names.get(t, "0x%08X" % t) if t < 0x801B0000 else "local"
                            break
                    code_refs[f["overlay"]][a - 0x801B0000].add(cal)
    data_refs = collections.defaultdict(set)
    for n, ov in by_ov.items():
        d = ov["data"]
        spans = [(s, e) for s, e, k in ov["segs"] if k == "data"]
        for s, e in spans:
            for i in range(s - s % 4 + (4 if s % 4 else 0), e - 3, 4):
                w = struct.unpack_from("<I", d, i)[0]
                if 0x801B0000 <= w < 0x801B0000 + len(d):
                    data_refs[n].add(w - 0x801B0000)
    kinds = collections.defaultdict(lambda: {"bytes": 0, "ovs": set(), "n": 0})
    zfill = collections.defaultdict(lambda: {"bytes": 0, "ovs": set(), "n": 0})
    zsizes = collections.Counter()
    half_sizes = collections.Counter()
    callee = collections.defaultdict(collections.Counter)

    def add(kind, nz, ov, n=1):
        k = kinds[kind]
        k["bytes"] += nz
        k["ovs"].add(ov)
        k["n"] += n
    for n, ov in by_ov.items():
        d = ov["data"]
        tims = tim_scan(d)
        mark = bytearray(len(d))
        for off, ln, _ in tims:
            mark[off:off + ln] = b"\x01" * ln
        for s0, e0, k in ov["segs"]:
            if k != "data":
                continue
            i = s0
            while i < e0:
                if not mark[i] and d[i] == 0:
                    seg = d[i:e0]
                    z = len(seg) - len(seg.lstrip(b"\0"))
                    if z >= 64:
                        refs_here = sorted(x for x in (set(code_refs[n]) | data_refs[n]) if i <= x < i + z)
                        # two 0xC000-byte buffers: code builds an address x and also x + 0xC000, both inside the run
                        pair = [x for x in refs_here if x in code_refs[n] and (x + 0xC000) in code_refs[n]]
                        both = bool(pair)
                        if pair:
                            half_sizes[hex(z)] += 1
                        shaped = 0x18000 <= z < 0x19000   # two 0xC000-byte buffers and a short tail
                        built = any(x in code_refs[n] for x in refs_here)
                        if shaped and both:
                            zk = "two 0xC000-byte buffers; code builds both bases"
                        elif shaped and built:
                            zk = "two 0xC000-byte buffers; code builds some other address inside"
                        elif shaped:
                            zk = "two 0xC000-byte buffers; no address inside built by code"
                        elif z >= 0x4000 and built:
                            zk = "other run of 16 KiB or more; code builds an address inside"
                        elif z >= 0x4000:
                            zk = "other run of 16 KiB or more; no address inside built by code"
                        else:
                            zk = "run under 16 KiB (64 bytes or more)"
                        zfill[zk]["bytes"] += z
                        zfill[zk]["ovs"].add(n)
                        zfill[zk]["n"] += 1
                        zsizes[z] += 1
                    i += max(z, 1)
                    continue
                if mark[i]:
                    i += 1
                    continue
                j = i
                while j < e0 and not mark[j] and not (d[j] == 0 and d[j:j + 64] == bytes(64)):
                    j += 1
                if j - i < 64:
                    add("short runs (under 64 bytes)", sum(1 for b in d[i:j] if b), n)
                    i = j
                    continue
                end = j
                used = bytearray(end - i)
                p = i
                while p < end:
                    L = sprite_len(d, p, end)
                    kind = "sprite"
                    if not L or L < 28:
                        L = model_len(d, p, end)
                        kind = "model"
                    if L and L >= 28 and not any(used[p - i:p - i + L]):
                        used[p - i:p - i + L] = b"\x01" * L
                        ref = p - 0 in data_refs[n] or p in code_refs[n]
                        nz = sum(1 for b in d[p:p + L] if b)
                        if kind == "sprite":
                            add("sprite-quad tables (SpriteAnim)", nz, n)
                            callee["sprite"]["address taken" if ref else "layout only"] += 1
                        else:
                            add("model blocks, address taken" if ref else "model blocks, layout only", nz, n)
                            for c in code_refs[n].get(p, ()):
                                callee["model"][c] += 1
                        p += L
                    else:
                        p += 4
                q = 0
                while q < end - i:
                    if used[q]:
                        q += 1
                        continue
                    r = q
                    while r < end - i and not used[r]:
                        r += 1
                    seg = d[i + q:i + r]
                    nz = sum(1 for b in seg if b)
                    if nz:
                        a = i + q
                        if len(seg) >= 32 and svector_like(seg) >= 0.7:
                            kind = "vertex-like arrays (s16 x, y, z, 0)"
                        elif a in code_refs[n]:
                            kind = "other, address built by code"
                        elif a in data_refs[n]:
                            kind = "other, pointed to from data"
                        else:
                            kind = "other, no reference found"
                        add(kind, nz, n)
                    q = r
                i = end
    return kinds, callee, zfill, zsizes, half_sizes


def run(magic_dir, table, battle, battle_vram, symbols, src, outdir):
    ovs, funcs, ovrows = measure(magic_dir, table)
    names = upstream_names(symbols) if symbols else {}
    N = {}
    byov = collections.defaultdict(list)
    for f in funcs:
        byov[f["overlay"]].append(f)
    # --- scale
    N["overlays"] = len(ovrows)
    N["overlays_sha1_ok"] = sum(r["sha_ok"] for r in ovrows)
    N["functions"] = len(funcs)
    N["code_bytes"] = sum(r["code"] for r in ovrows)
    N["data_bytes"] = sum(r["data"] for r in ovrows)
    N["file_bytes"] = sum(r["bytes"] for r in ovrows)
    N["bss_bytes_total"] = sum(r["bss"] for r in ovrows)
    N["vram_values"] = sorted({r["vram"] for r in ovrows})
    N["imports"] = dict(collections.Counter(r["imports"] for r in ovrows))
    fc = sorted(r["functions"] for r in ovrows)
    N["functions_per_overlay"] = {"min": fc[0], "median": fc[len(fc) // 2], "max": fc[-1]}
    cb = sorted(r["code"] for r in ovrows)
    N["code_bytes_per_overlay"] = {"min": cb[0], "median": cb[len(cb) // 2], "max": cb[-1]}
    db = sorted(r["data"] for r in ovrows)
    N["data_bytes_per_overlay"] = {"min": db[0], "median": db[len(db) // 2], "max": db[-1]}
    N["code_share_of_file"] = round(N["code_bytes"] / N["file_bytes"], 4)
    ex = sorted(ovrows, key=lambda r: r["code"])
    N["examples"] = {"smallest_code": [(r["overlay"], r["code"], r["data"]) for r in ex[:3]],
                     "largest_code": [(r["overlay"], r["code"], r["data"]) for r in ex[-3:]]}
    # --- split cross-check against the function list of the staged tree's source (INCLUDE_ASM lines + C definitions)
    import re
    agree = 0
    tot_src = 0
    for r in ovrows:
        pth = os.path.join(src, "src", "magic", r["overlay"] + ".c") if src else ""
        if not pth or not os.path.exists(pth):
            continue
        t = open(pth, encoding="utf-8", errors="replace").read()
        names_src = set(re.findall(r"INCLUDE_ASM\([^)]*[ ,](\w+)\);", t)) | set(
            re.findall(r"^[A-Za-z_][\w \t\*]*\b(\w+)\s*\([^;{]*\)\s*\{", t, re.M))
        tot_src += len(names_src)
        agree += 1 if len(names_src) == r["functions"] else 0
    N["split_check"] = {"overlays_same_count": agree, "functions_in_source": tot_src, "functions_split": len(funcs)}
    # --- families
    fams = families(funcs, "skel")
    clone_fams = families(funcs, "clone")
    bytes_f = lambda v: sum(x["n"] * 4 for x in v)  # noqa: E731
    cov_f = sum(len(v) for v in fams)
    cov_b = sum(bytes_f(v) for v in fams)
    N["skeleton_families"] = {"count": len(fams), "functions": cov_f, "bytes": cov_b,
                              "functions_share": round(cov_f / len(funcs), 4),
                              "bytes_share": round(cov_b / sum(f["n"] * 4 for f in funcs), 4)}
    big = [v for v in fams if v[0]["n"] >= MIN_FAMILY_INS]
    N["skeleton_families_ge10"] = {"count": len(big), "functions": sum(len(v) for v in big), "bytes": sum(bytes_f(v) for v in big)}
    N["clone_families"] = {"count": len(clone_fams), "functions": sum(len(v) for v in clone_fams),
                           "bytes": sum(bytes_f(v) for v in clone_fams)}
    in_any = {id(x) for v in fams for x in v}
    uniq = [f for f in funcs if id(f) not in in_any]
    N["duplicate_copies"] = {"bytes_beyond_first_copy": sum((len(v) - 1) * v[0]["n"] * 4 for v in fams),
                             "functions_beyond_first_copy": sum(len(v) - 1 for v in fams)}
    sets = collections.defaultdict(list)
    for v in fams:
        if len(v) >= 3 and v[0]["n"] >= 10:
            sets[frozenset(x["overlay"] for x in v)].append(v)
    grp = [(len(k), len(v), sum(len(x) * x[0]["n"] * 4 for x in v), sorted(k)[:5])
           for k, v in sets.items() if len(v) >= 2 and len(k) >= 5]
    grp.sort(key=lambda g: -g[2])
    N["overlay_groups_sharing_several_families"] = [
        {"overlays": a, "families": b, "bytes": c, "first_members": d} for a, b, c, d in grp[:6]]
    N["unique_functions"] = {"count": len(uniq), "bytes": sum(f["n"] * 4 for f in uniq)}
    N["unique_by_size"] = {"lt10": sum(1 for f in uniq if f["n"] < 10), "10to49": sum(1 for f in uniq if 10 <= f["n"] < 50),
                           "50to199": sum(1 for f in uniq if 50 <= f["n"] < 200), "ge200": sum(1 for f in uniq if f["n"] >= 200)}
    N["max_family_overlays"] = max(len({x["overlay"] for x in v}) for v in fams)
    # overlays: share of each overlay's code that is in a family
    share = []
    for o, fl in byov.items():
        t = sum(f["n"] for f in fl)
        c = sum(f["n"] for f in fl if id(f) in in_any)
        share.append(c / t if t else 0)
    share.sort()
    N["overlay_family_code_share"] = {"min": round(share[0], 3), "median": round(share[len(share) // 2], 3),
                                      "max": round(share[-1], 3)}
    N["overlays_with_ge_half_shared"] = sum(1 for x in share if x >= 0.5)
    # families table
    ext_calls_all = collections.Counter()
    rows = []
    for k, v in enumerate(fams, 1):
        n = v[0]["n"]
        ov_set = sorted({x["overlay"] for x in v})
        kinds = vary(v)
        cal = collections.Counter()
        use = collections.Counter()
        for x in v[:1]:
            a, j = refs(x["seq"])
            for t in j:
                if t < 0x801B0000:
                    cal[t] += 1
            for t in a:
                if t < 0x801B0000:
                    use[t] += 1
        callees = ",".join(names.get(t, "0x%08X" % t) for t in sorted(cal))
        uses = ",".join(names.get(t, "0x%08X" % t) for t in sorted(use))
        clone_n = len({x["clone"] for x in v})
        rows.append({"family": "F%03d" % k, "functions": len(v), "overlays": len(ov_set), "instructions": n, "bytes_each": n * 4,
                     "bytes_total": n * 4 * len(v), "clone_variants": clone_n,
                     "positions_varying": sum(kinds.values()), "addr_hi_varying": kinds.get("addr-hi", 0),
                     "imm_varying": kinds.get("imm", 0) + kinds.get("const", 0),
                     "first_offset": "0x%X" % v[0]["off"], "first_vram": "0x%08X" % v[0]["addr"],
                     "external_callees": callees, "external_data": uses[:300],
                     "example_overlays": ",".join(ov_set[:6]) + (",..." if len(ov_set) > 6 else "")})
    for f in funcs:
        a, j = refs(f["seq"])
        for t in set(j):
            if t < 0x801B0000:
                ext_calls_all[t] += 1
    # --- near families
    exact_keys = {x["skel"] for v in fams for x in v[:1]}
    near = near_families(funcs, exact_keys)
    N["near_families"] = {"count": len(near), "functions": sum(len(v) for v in near),
                          "bytes": sum(bytes_f(v) for v in near),
                          "note": "functions >= 20 instructions not in an exact family whose masked sequences are >= 85 percent alike in another overlay"}
    # --- skeleton of an overlay: entry stub, registered callbacks
    ENTRY_REG = 0x800BBEAC
    first_shape = collections.Counter()
    second_shape = collections.Counter()
    stub8 = 0
    stub_target_calls_register = 0
    reg_sites = []
    cb_counts = []
    for o, fl in byov.items():
        f0 = fl[0]
        a0, j0 = refs(f0["seq"])
        is_stub = f0["n"] == 8 and len(j0) == 1
        if is_stub:
            stub8 += 1
            tgt = [x for x in fl if x["addr"] == j0[0]]
            if tgt and ENTRY_REG in refs(tgt[0]["seq"])[1]:
                stub_target_calls_register += 1
        first_shape[(f0["skel"], f0["n"])] += 1
        if len(fl) > 1:
            second_shape[(fl[1]["skel"], fl[1]["n"])] += 1
        starts = {x["addr"] for x in fl}
        callbacks = set()
        regs = 0
        for f in fl:
            a, j = refs(f["seq"])
            regs += sum(1 for t in j if t == ENTRY_REG)
            for t in a:
                if t in starts:
                    callbacks.add(t)
        reg_sites.append(regs)
        cb_counts.append(len(callbacks))
    N["entry"] = {"first_function_is_8_instruction_stub_calling_one_function": stub8,
                  "stub_target_calls_BattleEffectRegister": stub_target_calls_register,
                  "first_function_shapes": [(h, n, c) for (h, n), c in first_shape.most_common(5)],
                  "overlays_with_distinct_first_shape": len(first_shape)}
    N["register_calls_per_overlay"] = dict(sorted(collections.Counter(reg_sites).items()))
    rs = sorted(reg_sites)
    N["register_calls"] = {"total": sum(rs), "median_per_overlay": rs[len(rs) // 2], "max": rs[-1]}
    cs = sorted(cb_counts)
    N["address_taken_functions_per_overlay"] = {"min": cs[0], "median": cs[len(cs) // 2], "max": cs[-1]}
    N["overlays_calling_BattleEffectRegister"] = sum(1 for x in reg_sites if x > 0)
    N["function_addresses_taken_per_overlay"] = dict(sorted(collections.Counter(cb_counts).items()))
    # the entry stub: the commonest 8-instruction function that makes exactly one call
    st = collections.Counter(f["skel"] for f in funcs if f["n"] == 8 and len(refs(f["seq"])[1]) == 1)
    stub_skel, stub_n = st.most_common(1)[0]
    stub_off = collections.Counter()
    stub_ov = 0
    for o, fl in byov.items():
        offs = [f["off"] for f in fl if f["skel"] == stub_skel]
        if offs:
            stub_ov += 1
            stub_off[offs[0]] += 1
    N["entry_stub"] = {"functions": stub_n, "overlays": stub_ov, "instructions": 8,
                       "first_stub_offsets": [("0x%X" % k, c) for k, c in stub_off.most_common(8)],
                       "distinct_offsets": len(stub_off)}
    N["entry_table_in_battle_exe"] = battle_table(battle, battle_vram)
    # a slot is freed by storing -1 as a halfword at +0 (addiu rt,zero,-1 ... sh rt,0(slot))
    term = 0
    term_ov = set()
    for f in funcs:
        sq = f["seq"]
        hit = False
        for i, w in enumerate(sq):
            if w >> 16 & 0xFC1F == 0x2400 and False:
                pass
            if op(w) == 9 and ((w >> 21) & 31) == 0 and (w & 0xFFFF) == 0xFFFF:
                rt = (w >> 16) & 31
                for w2 in sq[i + 1:i + 5]:
                    if op(w2) == 41 and ((w2 >> 16) & 31) == rt and (w2 & 0xFFFF) == 0:
                        hit = True
        if hit:
            term += 1
            term_ov.add(f["overlay"])
    N["functions_with_free_slot_store"] = {"count": term, "overlays": len(term_ov)}
    # idioms: reading the effect slot of the running effect (cursor at 0x8015169C, slot table at 0x80162978)
    CUR, SLOTS = 0x8015169C, 0x80162978
    users = [f for f in funcs if CUR in refs(f["seq"])[0]]
    N["functions_reading_effect_cursor"] = {"count": len(users), "overlays": len({f["overlay"] for f in users}),
                                           "bytes": sum(f["n"] * 4 for f in users)}
    N["functions_using_slot_table"] = len([f for f in funcs if SLOTS in refs(f["seq"])[0]])
    N["top_external_callees"] = [(names.get(t, "0x%08X" % t), "0x%08X" % t, c) for t, c in ext_calls_all.most_common(15)]
    # --- data
    tim_n = tim_b = tim_ov = 0
    hashes = collections.Counter()
    zero_b = 0
    ptr_words = 0
    data_total = 0
    nonzero_other = 0
    for ov in ovs:
        d = ov["data"]
        tims = tim_scan(d)
        if tims:
            tim_ov += 1
        tim_n += len(tims)
        tim_b += sum(t[1] for t in tims)
        for _, _, blob in tims:
            hashes[hashlib.sha1(blob).hexdigest()] += 1
        inside = bytearray(len(d))
        for off, ln, _ in tims:
            inside[off:off + ln] = b"\x01" * ln
        for s, e, k in ov["segs"]:
            if k != "data":
                continue
            blk = d[s:e]
            data_total += len(blk)
            zero_b += sum(1 for i, b in enumerate(blk) if b == 0 and not inside[s + i]) if False else 0
            for i in range(0, len(blk), 1):
                pass
            w = struct.unpack("<%dI" % (len(blk) // 4), blk[:len(blk) // 4 * 4])
            ptr_words += sum(1 for x in w if 0x801B0000 <= x < 0x801B0000 + len(d) + ov["bss"])
        # zero bytes outside TIMs, inside data segments
        for s, e, k in ov["segs"]:
            if k == "data":
                seg = d[s:e]
                z = seg.count(0)
                tz = 0
                for off, ln, blob in tims:
                    lo, hi = max(off, s), min(off + ln, e)
                    if hi > lo:
                        tz += d[lo:hi].count(0)
                zero_b += z - tz
    # what is left once TIM images and zero runs are set aside: non-zero runs of >= 64 bytes, by their first word
    blocks = collections.Counter()
    block_hash = collections.defaultdict(set)
    nblocks = bblocks = 0
    for ov in ovs:
        d = ov["data"]
        mark = bytearray(len(d))
        for off, ln, _ in tim_scan(d):
            mark[off:off + ln] = b"\x01" * ln
        for s0, e0, k in ov["segs"]:
            if k != "data":
                continue
            i = s0
            while i < e0:
                if mark[i] or d[i] == 0:
                    i += 1
                    continue
                j = i
                while j < e0 and not mark[j] and not (d[j] == 0 and d[j:j + 64] == bytes(64)):
                    j += 1
                if j - i >= 64:
                    w0 = d[i:i + 4].hex()
                    blocks[w0] += 1
                    block_hash[w0].add(hashlib.sha1(d[i:j]).hexdigest())
                    nblocks += 1
                    bblocks += j - i
                i = j
    dup_blocks = sum(c for c in hashes.values() if c > 1)
    N["data"] = {"bytes": data_total, "tim_images": tim_n, "tim_bytes": tim_b, "overlays_with_tim": tim_ov,
                 "distinct_tim_images": len(hashes), "tim_images_that_occur_in_more_than_one_overlay": dup_blocks,
                 "zero_bytes_outside_tim": zero_b, "pointer_words_into_own_range": ptr_words,
                 "other_bytes": data_total - tim_b - zero_b,
                 "other_blocks_ge64": nblocks, "other_blocks_bytes": bblocks,
                 "other_blocks_by_first_word": [(k, c, len(block_hash[k])) for k, c in blocks.most_common(5)]}
    # --- compiler
    hdr = {k: v for k, v in (src_headers(src) if src else {}).items() if k in {r["overlay"] for r in ovrows}}
    c = collections.Counter()
    cm = collections.Counter()
    for nme, (h, defd, asm) in hdr.items():
        c[h or "(none: default cc1-psx-272)"] += 1
        if defd:
            cm[h or "(none)"] += 1
    N["compiler_setting_files"] = dict(c)
    N["compiler_setting_files_with_matched_c"] = dict(cm)
    N["files_with_matched_c_functions"] = sum(1 for h, d, a in hdr.values() if d)
    N["functions_matched_in_c_in_staged_tree"] = sum(d for h, d, a in hdr.values())
    N["functions_still_asm_in_staged_tree"] = sum(a for h, d, a in hdr.values())
    kinds, callee, zfill, zsizes, half_sizes = data_kinds(ovs, funcs, names)
    total_nz = sum(k["bytes"] for k in kinds.values())
    N["data_kinds"] = {"non_zero_non_image_bytes": total_nz,
                       "rows": [{"kind": k, "bytes": v["bytes"], "share": round(v["bytes"] / total_nz, 4),
                                 "overlays": len(v["ovs"]), "items": v["n"]}
                                for k, v in sorted(kinds.items(), key=lambda kv: -kv[1]["bytes"])],
                       "model_blocks_first_routine_called_after_address": callee["model"].most_common(5),
                       "sprite_tables_start_addressed": dict(callee["sprite"]),
                       "zero_fill": [{"kind": k, "bytes": v["bytes"], "overlays": len(v["ovs"]), "runs": v["n"]}
                                     for k, v in sorted(zfill.items(), key=lambda kv: -kv[1]["bytes"])],
                       "zero_run_sizes_most_common": [(hex(k), c) for k, c in zsizes.most_common(8)],
                       "two_buffer_run_sizes_most_common": half_sizes.most_common(6)}
    # --- write
    os.makedirs(outdir, exist_ok=True)
    cols = list(rows[0].keys())
    with open(os.path.join(outdir, "MAGIC-OVERLAYS-FAMILIES.tsv"), "w", encoding="utf-8") as fh:
        fh.write("\t".join(cols) + "\n")
        for r in rows:
            fh.write("\t".join(str(r[c]) for c in cols) + "\n")
    with open(os.path.join(outdir, "MAGIC-OVERLAYS-OVERLAYS.tsv"), "w", encoding="utf-8") as fh:
        oc = ["overlay", "file", "vram", "sha1", "code_start", "code_end", "bss", "imports", "bytes", "code", "data", "functions"]
        fh.write("\t".join(oc) + "\n")
        for r in sorted(ovrows, key=lambda r: r["overlay"]):
            fh.write("\t".join(str(r[c]) for c in oc) + "\n")
    with open(os.path.join(outdir, "MAGIC-OVERLAYS-NUMBERS.json"), "w", encoding="utf-8") as fh:
        json.dump(N, fh, indent=1)
    return N, rows, near


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n", 1)[1])
    ap.add_argument("--magic", help="folder with the overlay .BIN files")
    ap.add_argument("--table", default=DEFAULT_TABLE, help="MAGIC-OVERLAYS-OVERLAYS.tsv")
    ap.add_argument("--battle", help="BATTLE.X.dec")
    ap.add_argument("--battle-vram", default="0x800A0000")
    ap.add_argument("--symbols", help="checkout whose config/symbols.*.txt name addresses")
    ap.add_argument("--src", help="tree with src/magic/*.c (optional)")
    ap.add_argument("--out", default=".", help="output folder")
    ap.add_argument("--make-table", metavar="US_YAML")
    a = ap.parse_args()
    if not a.magic:
        ap.error("--magic is required")
    if a.make_table:
        make_table(a.make_table, a.magic, os.path.join(a.out, "MAGIC-OVERLAYS-OVERLAYS.tsv"))
        return
    table = read_table(a.table)
    N, rows, near = run(a.magic, table, a.battle, int(a.battle_vram, 0), a.symbols, a.src, a.out)
    print(json.dumps(N, indent=1))
    print("\nfamilies (top %d by total bytes):" % TOP_FAMILIES)
    for r in sorted(rows, key=lambda r: -r["bytes_total"])[:TOP_FAMILIES]:
        print("  %s funcs=%d ov=%d ins=%d total=%d vary=%d (addr %d, imm %d) clone_variants=%d calls=%s uses=%s" % (
            r["family"], r["functions"], r["overlays"], r["instructions"], r["bytes_total"], r["positions_varying"],
            r["addr_hi_varying"], r["imm_varying"], r["clone_variants"], r["external_callees"][:90], r["external_data"][:90]))


if __name__ == "__main__":
    main()
