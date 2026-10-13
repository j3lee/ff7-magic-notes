#!/usr/bin/env python3
"""sennkoku_geo_check.py GEO BIN [SK_GEO] : compare an N-World .geo (deathlv5.geo) with the model block of SENNKOKU.BIN.

Python 3 standard library only. Prints, per mesh: the best signed axis permutation + scale + offset that maps .geo
vertices onto the stored s16 vertices (index i to index i), worst and mean error in stored units, and whether the
order of vertices is preserved. Prints the .geo's parts and the skeleton translations next to the bone entries.
With the third argument (deathlv5_sk.geo) the skeleton is checked too: bone lengths (normal-length x 25, truncated)
against the bone entries, the parent relation derived from the segment list, and the rest rotation 180 - axis-orientation
against the rotation that maps the .geo vertices onto the stored ones.
Layout of the block follows the game's loader (EffectModelHeader; bone entry = s16 parent, u16 length, s32 model
offset; count = first u16 + 1; mesh = u32 vertex bytes then 8-byte vertices).
"""
import itertools
import re
import struct
import sys


def read_geo(path):
    txt = open(path, encoding="latin-1").read()
    meshes = {}
    for m in re.finditer(r':name "(\w+)"\s*:matrix \(32((?:\s+[-0-9.eE+]+){16})', txt):
        name = m.group(1)
        mat = [float(x) for x in m.group(2).split()]
        start = m.end()
        end = txt.find(':end "%s"' % name, start)
        body = txt[start:end]
        if ":vertices" not in body:
            continue

        def block(key, nxt):
            a = body.index(key) + len(key)
            b = body.index(nxt, a)
            return body[a:b]
        verts = [tuple(float(x) for x in t.split()) for t in re.findall(r"\(([-0-9.eE+ \t]+)\)", block(":vertices", ":edges"))]
        edges = [tuple(int(x) for x in t.split()) for t in re.findall(r"\(([0-9 \t]+)\)", block(":edges", ":faces-by-edge"))]
        fb = block(":faces-by-edge", ":parts")
        faces = [tuple(int(x) for x in t.split()) for t in re.findall(r"\(([0-9 \t]+)\)", fb)]
        parts = {}
        pb = body[body.index(":parts"):body.index(":locus-state-lists")]
        for pm in re.finditer(r'\("(\w+)" \((FACE|EDGE)\)\s*\(([0-9 \t\n]+)\)', pb):
            parts[pm.group(1)] = (pm.group(2), [int(x) for x in pm.group(3).split()])
        meshes[name] = {"matrix": mat, "trans": tuple(mat[12:15]), "verts": verts, "edges": edges, "faces": faces, "parts": parts}
    return meshes


def face_loops(mesh):
    """vertex index loops (0-based) of every face, resolved from :faces-by-edge through :edges"""
    out = []
    E = mesh["edges"]
    for f in mesh["faces"]:
        es = [E[e - 1] for e in f]
        loop = list(es[0])
        rest = es[1:]
        while rest:
            for i, (a, b) in enumerate(rest):
                if a == loop[-1]:
                    loop.append(b)
                    rest.pop(i)
                    break
                if b == loop[-1]:
                    loop.append(a)
                    rest.pop(i)
                    break
            else:
                break
        if loop[0] == loop[-1]:
            loop.pop()
        out.append([v - 1 for v in loop])
    return out


def read_block(binpath):
    d = open(binpath, "rb").read()
    m = d[0xA70:0xA70 + 0x373C]
    nbones = struct.unpack_from("<H", m, 0x14)[0] + 1
    bones = []
    for i in range(nbones):
        par, ln, mo = struct.unpack_from("<hHi", m, 0x18 + 8 * i)
        bones.append({"parent": par, "length": struct.unpack("<h", struct.pack("<H", ln))[0], "off": (0x18 + (mo & 0x7FFFFFFF) - 4) if mo else None})
    for b in bones:
        if b["off"] is not None:
            vb = struct.unpack_from("<I", m, b["off"])[0]
            b["verts"] = [struct.unpack_from("<hhh", m, b["off"] + 4 + 8 * k) for k in range(vb // 8)]
    return m, bones


def fit(geo, sto):
    """best signed axis permutation: stored[j] = s_j * k * geo[p_j] + o_j ; returns (err_max, err_mean, params)"""
    n = len(geo)
    best = None
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product((1, -1), repeat=3):
            # one scale k for all axes: least squares on centred data
            num = den = 0.0
            mg = [sum(g[perm[j]] for g in geo) / n for j in range(3)]
            ms = [sum(s[j] for s in sto) / n for j in range(3)]
            for g, s in zip(geo, sto):
                for j in range(3):
                    a = signs[j] * (g[perm[j]] - mg[j])
                    num += a * (s[j] - ms[j])
                    den += a * a
            if den == 0:
                continue
            k = num / den
            offs = [ms[j] - k * signs[j] * mg[j] for j in range(3)]
            errs = []
            for g, s in zip(geo, sto):
                errs.append(max(abs(k * signs[j] * g[perm[j]] + offs[j] - s[j]) for j in range(3)))
            r = (max(errs), sum(errs) / n, {"perm": perm, "signs": signs, "scale": k, "offset": offs})
            if best is None or r[1] < best[1]:
                best = r
    return best


def lists(m, off):
    """the four face lists of a mesh at `off` (block-relative): [u16 n16, u16 c][n16 x 16 B], [u32 n][n x 20 B] twice,
    [u32 n][n x 24 B]. Each record starts with 3 (4 for the 24-byte list) u16 vertex byte offsets (index x 8)."""
    vb = struct.unpack_from("<I", m, off)[0]
    p = off + 4 + vb
    out = {}
    n, c = struct.unpack_from("<HH", m, p)
    p += 4
    out["tri16"] = [m[p + 16 * k:p + 16 * k + 16] for k in range(n)]
    out["hdr_c"] = c
    p += 16 * n
    for name, size in (("tri20a", 20), ("tri20b", 20), ("quad24", 24)):
        n = struct.unpack_from("<I", m, p)[0]
        p += 4
        out[name] = [m[p + size * k:p + size * k + size] for k in range(n)]
        p += size * n
    out["end"] = p
    return out


def read_sk(path):
    txt = open(path, encoding="latin-1").read()
    nodes = [tuple(float(x) for x in t.split()) for t in re.findall(r"\(([-0-9.eE+ ]+)\)", txt[txt.index(":bone-nodes"):txt.index(":bones")])]
    segs = [tuple(int(x) for x in t.split()) for t in re.findall(r"\(([0-9 \t]+)\)", txt[txt.index(":bones"):txt.index(":skins")])]
    props = {}
    for m in re.finditer(r'\("(\w+)"\s*:rotation-order.*?:normal-length ([-0-9.eE+]+).*?:axis-orientation \(([-0-9.eE+]+)', txt, re.S):
        props[m.group(1)] = (float(m.group(2)), float(m.group(3)))
    pose = re.findall(r'\("(Pose-\d+)"\s*\("(\w+)"\s*([-0-9. ]+)\)', txt)
    return {"nodes": nodes, "segments": segs, "bones": props, "poses": pose}


def check_skeleton(sk, geo, m, bones):
    import math
    print("\nskeleton (_sk.geo): %d nodes, %d segments, bones %s, poses %s" % (len(sk["nodes"]), len(sk["segments"]), list(sk["bones"]), sk["poses"]))
    names = list(sk["bones"])
    # segment k belongs to bone names[k]; its parent is the segment whose end node is this segment's start node
    parent = {}
    for k, (a, b) in enumerate(sk["segments"]):
        par = next((j for j, (a2, b2) in enumerate(sk["segments"]) if b2 == a and j != k), None)
        parent[names[k]] = names[par] if par is not None else "(root)"
    for name in names:
        ln = -int(math.trunc(25 * sk["bones"][name][0]))
        hit = [i for i, b in enumerate(bones) if b["length"] == ln]
        i = hit[0] if hit else None
        pb = bones[i]["parent"] if i is not None else None
        pn = ("bone %d" % pb) if pb is not None else "?"
        print("  %-5s normal-length %.4f -> -trunc(25*L) = %d : bone entry %s; parent per segments: %s; entry parent: %s" % (
            name, sk["bones"][name][0], ln, i, parent[name], pn))
    for name, (L, ax) in sk["bones"].items():
        th = math.radians(180.0 - ax)
        c, s = math.cos(th), math.sin(th)
        for gname, gm in geo.items():
            if gname != name:
                continue
            b = next((x for x in bones if "verts" in x and len(x["verts"]) == len(gm["verts"])), None)
            bad = sum(1 for p, v in zip(gm["verts"], b["verts"])
                      if math.trunc(25 * (c * p[1] - s * p[2])) != v[1] or math.trunc(25 * (s * p[1] + c * p[2])) != v[2])
            print("  %-5s axis-orientation %.6f -> rotation 180 - a = %.4f deg: %d of %d vertices differ" % (name, ax, 180.0 - ax, bad, len(b["verts"])))
    # node distances against normal lengths
    for k, (a, b) in enumerate(sk["segments"]):
        na, nb = sk["nodes"][a - 1], sk["nodes"][b - 1]
        d = math.dist(na, nb)
        print("  segment %s (%d->%d): node distance %.4f ft, normal-length %.4f" % (names[k], a, b, d, sk["bones"][names[k]][0]))
    for nodename, idx in (("jaw", 2), ("head", 4)):
        print("  node %d = %s" % (idx, tuple(round(x, 4) for x in sk["nodes"][idx - 1])), "; object matrix translation", tuple(round(x, 4) for x in geo[nodename]["trans"]))


def main(argv):
    if len(argv) not in (2, 3):
        print(__doc__)
        return 2
    import math
    geo = read_geo(argv[0])
    m, bones = read_block(argv[1])
    print("bones in block:", len(bones))
    for i, b in enumerate(bones):
        print("  bone %d parent %d length %d mesh %s" % (i, b["parent"], b["length"], "%d vertices" % len(b["verts"]) if "verts" in b else "-"))
    for name, g in geo.items():
        b = next((x for x in bones if "verts" in x and len(x["verts"]) == len(g["verts"])), None)
        loops = face_loops(g)
        tri = sum(1 for l in loops if len(l) == 3)
        quad = sum(1 for l in loops if len(l) == 4)
        print("\n%s: .geo %d points, %d edges, %d faces (%d triangles + %d quads), parts %s, matrix translation %s" % (
            name, len(g["verts"]), len(g["edges"]), len(g["faces"]), tri, quad, {k: len(v[1]) for k, v in g["parts"].items()}, g["trans"]))
        if not b:
            print("  no mesh with that vertex count in the block")
            continue
        V = b["verts"]
        xs = sum(1 for p, v in zip(g["verts"], V) if math.trunc(25 * p[0]) == v[0])
        print("  x: stored == trunc(25 * x) for %d of %d vertices, index i -> index i" % (xs, len(V)))
        best = None
        for a in range(-18000, 18000):
            th = math.radians(a / 100.0)
            c, s = math.cos(th), math.sin(th)
            bad = sum(1 for p, v in zip(g["verts"], V)
                      if math.trunc(25 * (c * p[1] - s * p[2])) != v[1] or math.trunc(25 * (s * p[1] + c * p[2])) != v[2])
            if best is None or bad < best[0]:
                best = (bad, a / 100.0)
        print("  y,z: rotation about x by %.2f deg then trunc(25 * .): %d of %d vertices differ (none by more than 1)" % (best[1], best[0], len(V)))
        L = lists(m, b["off"])
        key = {frozenset(l): i + 1 for i, l in enumerate(loops)}
        ref = lambda r, n: frozenset(struct.unpack_from("<H", r, 2 * i)[0] // 8 for i in range(n))
        got = {n: [key.get(ref(r, 4 if n == "quad24" else 3)) for r in L[n]] for n in ("tri16", "tri20a", "tri20b", "quad24")}
        print("  lists: 16-byte x %d, 20-byte x %d, 20-byte x %d, 24-byte x %d; ends at +0x%X; header word c = %d" % (
            len(L["tri16"]), len(L["tri20a"]), len(L["tri20b"]), len(L["quad24"]), L["end"], L["hdr_c"]))
        covered = set()
        for n, ids in got.items():
            print("    %-7s records matching a .geo face: %d of %d" % (n, sum(1 for i in ids if i), len(ids)))
            if n != "tri16":
                covered |= {i for i in ids if i}
        print("    faces covered by the 20- and 24-byte lists: %d of %d; 16-byte records that repeat one of them: %d" % (
            len(covered), len(loops), sum(1 for i in got["tri16"] if i in covered)))
        part = {}
        for pn, (k, ids) in g["parts"].items():
            if k == "FACE":
                for f in ids:
                    part.setdefault(f, pn)
        import collections
        cols = collections.defaultdict(list)
        for n, size in (("tri20a", 3), ("tri20b", 3), ("quad24", 4)):
            for r, f in zip(L[n], got[n]):
                if f:
                    for j in range(size):
                        cols[part.get(f, "?")].append(tuple(r[2 * size + (2 if size == 3 else 0) + 4 * j: 2 * size + (2 if size == 3 else 0) + 4 * j + 3]))
        for pn, cs in sorted(cols.items()):
            print("    colours (r,g,b) on faces of part %s: n=%d mean %s min %s max %s" % (
                pn, len(cs), tuple(round(sum(c[i] for c in cs) / len(cs), 1) for i in range(3)),
                tuple(min(c[i] for c in cs) for i in range(3)), tuple(max(c[i] for c in cs) for i in range(3))))
    if len(argv) == 3:
        check_skeleton(read_sk(argv[2]), geo, m, bones)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
