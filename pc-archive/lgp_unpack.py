#!/usr/bin/env python3
"""lgp_unpack.py : unpack (or list) an FF7 .lgp archive. Python 3 standard library only.

  lgp_unpack.py ARCHIVE OUTDIR [--list] [--only GLOB]
  lgp_unpack.py --self-test

Written from the Qhimm wiki description of the format ('FF7/LGP format'):
  header     12-byte creator string, u32 file count
  TOC        count x { char name[20], u32 offset, u8 check, u16 conflict }      (27 bytes each)
  lookup     30 x 30 x { u16 toc index, u16 count }                              (hash table; not needed to unpack)
  conflicts  u16 table count, then per table: u16 entries, entries x { char path[128], u16 toc index }
  data       at each offset: char name[20], u32 length, length bytes
  trailer    "FINAL FANTASY7" (optional)
A TOC entry whose conflict field is non-zero has its folder in the path table: each table row is (char folder[128],
u16 TOC index, 0-based) and the file's path is folder + "/" + its TOC name (verified on FF7's magic.lgp: all 2,450
entries with a non-zero conflict field are referenced exactly once, and 652 names repeat across folders). Entries
without a folder go to the top of OUTDIR. If two entries still resolve to one path the later ones get a `.dupN` suffix
before the extension and are reported on stderr. Anything that would land outside OUTDIR is refused.
--list prints `offset length path` per file and writes nothing. --only takes an fnmatch glob tried against the full
path and against the bare file name (case-insensitive).
"""
import fnmatch
import os
import struct
import sys

TOC_ENTRY = 27
LOOKUP_BYTES = 30 * 30 * 4
TRAILER = b"FINAL FANTASY7"


class LgpError(Exception):
    pass


def _cstr(b):
    return b.split(b"\0", 1)[0].decode("latin-1")


def parse(data):
    """-> (creator, [ {name, path, offset, length, check, conflict} ])"""
    if len(data) < 16:
        raise LgpError("file too short for an LGP header")
    creator = _cstr(data[:12])
    (count,) = struct.unpack_from("<I", data, 12)
    toc_end = 16 + count * TOC_ENTRY
    if count > 0x100000 or toc_end > len(data):
        raise LgpError("file count %d does not fit the file" % count)
    ents = []
    for i in range(count):
        name_b, off, chk, conf = struct.unpack_from("<20sIBH", data, 16 + i * TOC_ENTRY)
        ents.append({"name": _cstr(name_b), "offset": off, "check": chk, "conflict": conf, "path": None, "length": None})
    # path table: optional, tolerate absence or truncation
    pos = toc_end + LOOKUP_BYTES
    folders = {}   # toc index (0-based) -> folder path
    if pos + 2 <= len(data):
        (ntab,) = struct.unpack_from("<H", data, pos)
        pos += 2
        for _ in range(ntab):
            if pos + 2 > len(data):
                break
            (n,) = struct.unpack_from("<H", data, pos)
            pos += 2
            for _ in range(n):
                if pos + 130 > len(data):
                    break
                p_b, idx = struct.unpack_from("<128sH", data, pos)
                pos += 130
                if 0 <= idx < count and idx not in folders:
                    folders[idx] = _cstr(p_b).replace("\\", "/").strip("/")
    for i, e in enumerate(ents):
        if e["offset"] + 24 > len(data):
            raise LgpError("entry %d (%s): data offset 0x%X outside the file" % (i, e["name"], e["offset"]))
        nm = _cstr(data[e["offset"]:e["offset"] + 20])
        (ln,) = struct.unpack_from("<I", data, e["offset"] + 20)
        if e["offset"] + 24 + ln > len(data):
            raise LgpError("entry %d (%s): length %d runs past the end of the file" % (i, e["name"], ln))
        if nm.lower() != e["name"].lower():
            raise LgpError("entry %d: TOC name %r but data header says %r" % (i, e["name"], nm))
        e["length"] = ln
        e["path"] = (folders[i] + "/" + e["name"]) if i in folders else e["name"]
    seen = {}
    for e in ents:
        k = e["path"].lower()
        if k in seen:
            seen[k] += 1
            stem, dot, ext = e["path"].rpartition(".") if "." in e["path"].rsplit("/", 1)[-1] else (e["path"], "", "")
            e["path"] = "%s.dup%d%s%s" % (stem, seen[k], dot, ext)
            e["renamed"] = True
        else:
            seen[k] = 0
    return creator, ents


def safe_join(outdir, rel):
    """join rel under outdir; raise LgpError when it would leave outdir or is absolute"""
    if not rel or rel.startswith("/") or (len(rel) > 1 and rel[1] == ":"):
        raise LgpError("refusing absolute or empty path %r" % rel)
    parts = [p for p in rel.replace("\\", "/").split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts) or not parts:
        raise LgpError("refusing path that escapes the output folder: %r" % rel)
    root = os.path.realpath(outdir)
    dest = os.path.realpath(os.path.join(root, *parts))
    if dest != root and not dest.startswith(root + os.sep):
        raise LgpError("refusing path that escapes the output folder: %r" % rel)
    return dest


def matches(e, pattern):
    if pattern is None:
        return True
    pat = pattern.lower()
    return fnmatch.fnmatchcase(e["path"].lower(), pat) or fnmatch.fnmatchcase(e["name"].lower(), pat)


def unpack(archive, outdir, list_only=False, only=None, out=sys.stdout):
    data = open(archive, "rb").read()
    creator, ents = parse(data)
    n = 0
    for e in ents:
        if not matches(e, only):
            continue
        if e.get("renamed"):
            print("lgp_unpack: path collision, kept as %s" % e["path"], file=sys.stderr)
        if list_only:
            print("0x%08X %9d %s" % (e["offset"], e["length"], e["path"]), file=out)
        else:
            dest = safe_join(outdir, e["path"])
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as fh:
                fh.write(data[e["offset"] + 24:e["offset"] + 24 + e["length"]])
        n += 1
    return creator, len(ents), n


# ---- builder, used by the self-test only --------------------------------------------------------------------------

def _bucket(ch):
    c = ch.lower()
    return ord(c) - ord("a") if "a" <= c <= "z" else 26


def build(files, creator="SQUARESOFT"):
    """files: list of (path, bytes). The TOC keeps the bare name; entries that have a folder get a conflict field equal to
    the 1-based number of the path table that lists all entries of that name (as FF7's own archives do)."""
    names = [p.rsplit("/", 1)[-1] for p, _ in files]
    count = len(files)
    toc_size = 16 + count * TOC_ENTRY
    groups = {}
    for i, (p, _) in enumerate(files):
        if "/" in p:
            groups.setdefault(names[i], []).append(i)
    tab_no = {n: k + 1 for k, n in enumerate(groups)}
    conf_bytes = struct.pack("<H", len(groups))
    for n, idxs in groups.items():
        conf_bytes += struct.pack("<H", len(idxs))
        for i in idxs:
            folder = files[i][0].rsplit("/", 1)[0]
            conf_bytes += struct.pack("<128sH", folder.encode("latin-1"), i)
    data_start = toc_size + LOOKUP_BYTES + len(conf_bytes)
    offs, blobs, cur = [], [], data_start
    for (p, d), nm in zip(files, names):
        offs.append(cur)
        blob = struct.pack("<20sI", nm.encode("latin-1"), len(d)) + d
        blobs.append(blob)
        cur += len(blob)
    head = struct.pack("<12sI", creator.encode("latin-1"), count)
    toc = b"".join(struct.pack("<20sIBH", nm.encode("latin-1"), o, 0x0E, tab_no.get(nm, 0) if "/" in p else 0)
                   for (p, _), nm, o in zip(files, names, offs))
    look = [[0, 0] for _ in range(900)]
    for i, nm in enumerate(names):
        k = _bucket(nm[0]) * 30 + (_bucket(nm[1]) if len(nm) > 1 else 0)
        if look[k][1] == 0:
            look[k][0] = i + 1
        look[k][1] += 1
    lookup = b"".join(struct.pack("<HH", a, b) for a, b in look)
    return head + toc + lookup + conf_bytes + b"".join(blobs) + TRAILER


def self_test():
    import io
    import tempfile
    files = [("lvl5death.s", b"(frame 12)\n(sound 420)\n"), ("lvl5death.dat", bytes(range(256)) * 3),
             ("sub/dir/magic.p", b"\x00\x01\x02"), ("EMPTY.S", b""),
             # a real three-way name collision, three folders, one of them nested
             ("ff7/magic/bio4/01.p", b"bio4-p"), ("ff7/limit/eva/01.p", b"eva-p"), ("ff7/summon/odin1/01.p", b"odin-p"),
             ("ff7/magic/bio4/01.rsd", b"bio4-rsd"), ("ff7/limit/eva/01.rsd", b"eva-rsd"),
             # a folderless entry with the same name as the folder ones
             ("01.p", b"top-p")]
    blob = build(files)
    with tempfile.TemporaryDirectory() as td:
        arc = os.path.join(td, "t.lgp")
        open(arc, "wb").write(blob)
        out = os.path.join(td, "out")
        creator, total, wrote = unpack(arc, out)
        assert creator == "SQUARESOFT" and total == len(files) and wrote == len(files), (creator, total, wrote)
        for p, d in files:
            got = open(os.path.join(out, *p.split("/")), "rb").read()
            assert got == d, p
        buf = io.StringIO()
        unpack(arc, out, list_only=True, only="LVL5*", out=buf)
        assert buf.getvalue().count("\n") == 2, buf.getvalue()
        buf = io.StringIO()
        unpack(arc, out, list_only=True, only="01.p", out=buf)
        assert buf.getvalue().count("\n") == 4 and "ff7/limit/eva/01.p" in buf.getvalue(), buf.getvalue()
        # two entries that resolve to the same path: the second is suffixed, nothing is overwritten
        same = build([("a/x.s", b"one"), ("a/x.s", b"two")])
        arc3 = os.path.join(td, "same.lgp")
        open(arc3, "wb").write(same)
        out3 = os.path.join(td, "o4")
        unpack(arc3, out3)
        assert open(os.path.join(out3, "a", "x.s"), "rb").read() == b"one"
        assert open(os.path.join(out3, "a", "x.dup1.s"), "rb").read() == b"two"
        # an entry whose path climbs out of the folder is refused and nothing is written outside
        evil = build([("../evil.s", b"x")])
        arc2 = os.path.join(td, "evil.lgp")
        open(arc2, "wb").write(evil)
        try:
            unpack(arc2, os.path.join(td, "o2"))
            raise AssertionError("escape not refused")
        except LgpError:
            pass
        assert not os.path.exists(os.path.join(td, "evil.s"))
        for bad in ("/etc/x", "a/../../x", ""):
            try:
                safe_join(os.path.join(td, "o3"), bad)
                raise AssertionError("not refused: %r" % bad)
            except LgpError:
                pass
        try:
            parse(blob[:len(blob) // 2])
            raise AssertionError("truncation accepted")
        except LgpError:
            pass
    print("self-test ok")


def main(argv):
    if argv[:1] == ["--self-test"]:
        self_test()
        return 0
    args = [a for a in argv if not a.startswith("--")]
    only = None
    if "--only" in argv:
        i = argv.index("--only")
        only = argv[i + 1]
        args = [a for a in args if a != only]
    list_only = "--list" in argv
    if len(args) < (1 if list_only else 2):
        print(__doc__)
        return 2
    try:
        creator, total, n = unpack(args[0], args[1] if len(args) > 1 else ".", list_only, only)
    except LgpError as e:
        print("lgp_unpack: %s" % e, file=sys.stderr)
        return 1
    print("%s: creator %r, %d files in archive, %d %s" % (args[0], creator, total, n, "listed" if list_only else "written"),
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
