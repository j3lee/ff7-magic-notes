# deathlv5: an N-World source asset left in the PC release, matched to the PS1 overlay

Findings as of 2026-10-13. halkun pointed at these files; everything below was then checked against the
bytes of the PS1 disc and the PC archive.

## The short version

1. The PC release's `magic.lgp` holds exactly three Lisp source files, all for one object, `deathlv5`
   (plus a 147-byte `deathlv5.hrc` naming the same three bones with the same lengths). There are no others
   anywhere in the PC data.
2. That object is the skull model of **Death Sentence / Roulette** (PS1 overlay `SENNKOKU.BIN`), not Level 5
   Death, despite its name.
3. The match is exact: all 303 vertices, all 534 faces, all 3 bone lengths and both rest rotations follow from
   the source files by one rule, **25 stored units per foot, truncated**.
4. This proves the model pipeline for this one spell (N-World to PS1 model block) and decodes the model
   block's face lists. It does **not** show how the effect's C code was written: no logic is in these files.

## Where the files are

| | |
|---|---|
| Archive | PC re-release, `data/battle/magic.lgp`, 51,094,486 bytes, 5,252 entries |
| `deathlv5.geo` | 34,557 bytes, geometry |
| `deathlv5_sk.geo` | 2,451 bytes, skeleton |
| `script-1.script` | 23,930 bytes, animation script |
| Header of both `.geo` files | `Mode: Lisp; Syntax: CLtL; Package: 3d`, dated 17 Jul 1996, 5:25 pm, `:units FEET` |
| Project path inside them | `/1d/proj/ff7/CG_OBJ/effect_chara/deathlv5/geo/` |

How "exactly three" was established: the whole PC data tree (1,991 files, 54 `.lgp` archives, 3.1 GB) was
searched for the markers `IN-PACKAGE`, `Mode: Lisp`, `DYNA::`, `CG_OBJ`, `effect_chara` and
`:body POLYHEDRON`. Every hit is inside `magic.lgp`, and inside it they fall in these three entries only.

The archive also has 806 entries ending in `.s`. They are binary data, not scripts.

The tool is Nichimen **N-World** (Lisp-based; N-Geometry for the `.geo` files, N-Dynamics for the script). The
package names in the files (`3D`, `DYNA`, `SP`) fit, N-World is documented as used on Final Fantasy VII, and
an N-Dynamics tutorial describes the same `Update Skeleton` operation the script calls. The files themselves
do not name the product.

## What each file holds

**`deathlv5.geo`**: a group of two polyhedra with every vertex, edge and face written out.

| Part | Points | Edges | Faces | Triangles | Quads | Named sub-parts |
|---|---|---|---|---|---|---|
| `jaw` | 91 | 251 | 162 | 146 | 16 | `skin`, `HARDEDGE` (24 edges) |
| `head` | 212 | 582 | 372 | 324 | 48 | `BL` (24 faces), `BL2` (2), `skin` (346), `HARDEDGE` (110 edges) |

Each sub-part has a diffuse colour (skin 0.245, 0.222, 0.199; `BL` 0.1 grey; `BL2` 0.174 grey). The surface
context is tagged `:PSX` with `:LIGHT-CALCULATION NIL`.

**`deathlv5_sk.geo`**: a skeleton of 4 nodes and 3 segments, with three bones.

| Bone | `:normal-length` | `:axis-orientation` (x) | Skin |
|---|---|---|---|
| `jaw` | 17.573845 | 61.848953 | the `jaw` polyhedron |
| `none` | 3.3178074 | 61.84292 | none |
| `head` | 45.797066 | -162.75816 | the `head` polyhedron |

One pose, `Pose-1`: `jaw` at 0.5.

**`script-1.script`**: one N-Dynamics script at 30 frames per second whose end time is 0.0333 s, which is one
frame. Three actions run in parallel across it: make `deathlv5` visible, update the skeleton `deathlv5_sk`,
and set `Pose-1` at value 1.0. It has no other cues: no sound, no hit, no particle, no timeline.

## The PS1 side

`SENNKOKU.BIN` is loaded for enemy skills 0x5C (Death Sentence) and 0x5D (Roulette). It is 120,304 bytes, of
which 2,352 are code (7 functions). Its entry functions return a model at 0x801B0A70: a 14,140-byte block
holding a skeleton section (13,788 bytes), a 68-byte script block and a 264-byte animation section. The
skeleton section has 4 bone entries (parents 0, 0, 0, 2), two of which carry a mesh.

Level 5 Death has its own overlay, `LV5DETH.BIN` (enemy skill 0x5B). It contains no skeleton model at all, only
a ring and a sprite, so `deathlv5` cannot be its asset. The object was filed under one spell's name and used
by another.

## The match

**Vertices.** The block stores 212 and 91 vertices as 8 bytes each (three signed 16-bit values and a zero).

| | Rule | Result |
|---|---|---|
| x | stored = truncate(25 × x) | jaw 91 of 91; head 211 of 212 (vertex 37: −33.00125 in the file, stored −32) |
| y, z | rotate about the x axis by the bone's rest angle, then truncate(25 × value) | jaw: 0 of 91 differ; head: 0 of 212 differ |
| Order | index i in the file is index i in the block | preserved for all 303 |

**Rotations.** The rotation applied to each part is its bone's rest angle from the skeleton file:
jaw 180 − 61.848953 = 118.151°, head 180 − (−162.75816) = 342.758° (that is, −17.242°). With the exact angles
no y or z value differs.

**Skeleton.**

| Bone | Length × 25 | Stored in the block |
|---|---|---|
| `jaw` | 439.3 | −439 |
| `none` | 82.9 | −82 |
| `head` | 1144.9 | −1144 |

The mesh-less entry in the block (parent of the jaw mesh) is the file's `none` bone. The parents agree too:
in the file `head` and `none` start at the root node and `jaw` starts where `none` ends; the block's entries
have parents 0, 0 and 2. The block lists the bones in the reverse of the file's order (head, none, jaw).

**Faces.** Every face in the file is in the block, matched by its set of vertices: head 324 triangles and 48
quads (372), jaw 146 and 16 (162).

## What this decodes: the model block's face lists

After the vertices, each mesh has four lists. Vertices are referenced by byte offset (index × 8).

| Record size | Contents | In this model |
|---|---|---|
| 16 bytes | textured triangles (texture coordinates) | head 22, jaw 0 |
| 20 bytes | textured quads | 0 (none in this model) |
| 20 bytes | coloured triangles, colour per vertex, command byte 0x30 | head 324, jaw 146 |
| 24 bytes | coloured quads, command byte 0x38 | head 48, jaw 16 |

The 22 textured triangles in the head repeat 22 of its gouraud triangles. This is the layout the battle
model renderer (`BattleDrawModel`, 0x800D29D4) reads, and blocks of the same layout make up about two thirds
of the non-image data across the 287 spell overlays, so it applies well beyond this spell.

## What the exporter changed

| Only in the source files | Only in the PS1 block |
|---|---|
| edges, sub-part names, the `HARDEDGE` sets | per-vertex colours with lighting baked in (about 0.74 of the part's diffuse colour, same hue) |
| diffuse colours as such, units, matrices, object names | GPU command bytes |
| the `:PSX` and lighting flags | the 22-triangle textured list with its texture coordinates |
| | the bone parent table and the animation record |

## Not explained

- (Since explained: the header value 44 in both meshes is a texture page. The model renderer reads it as the
  second halfword of the first face-list header and adds it to the descriptor's texture page.)
- The two dark sub-parts (`BL`, `BL2`) are stored with a blue tint that their grey diffuse colours do not give.
- The 22 textured triangles: the source has no texture coordinates for them.
- The animation record in the block (264 bytes) was not decoded, so `Pose-1` (jaw at 0.5) is not checked
  against it.
- Why the block lists the bones in reverse order.

## What it does and does not show

**Shows:** for this spell, the model went from an artist's N-World files of July 1996 to the PS1 overlay with
a fixed scale, rest rotations taken from the skeleton, and lighting baked in.

**Does not show:** that the effect's C code was generated from a script. The script is one frame with no
events; none of the overlay's own numbers (hit frames 1, 17, 32, 36, 50; the Roulette spin constants; sound
ids) appear in any of the three files. What the overlay code does show, from the binaries alone, is copying
between overlays: its buffer-flip function is identical in 76 overlays (and unused here), and its hit timeline
is instruction-identical to another spell's.

**Cannot be taken further from the PC release:** these files are the only source assets in it.

## The rest of the PC archive against the PS1 overlays

The same archive, unpacked in full (5,252 entries), lines up with the PS1 spell data well beyond this one
object.

| PC files | What they are | Against the PS1 overlays |
|---|---|---|
| 806 `.s` | sprite-frame tables (a 0x2023 marker, a frame count, then 0x14-byte quads); all 806 parse to the last byte | 760 are byte-identical to a run inside a PS1 overlay (212 overlays); 6 more differ only in a texture-page value; 40 have no counterpart |
| 343 `.p` in folders or files named like an overlay | polygon models | in 281 of them (85 overlays) every vertex equals truncate(scale × vertex) of a PS1 model block of that overlay |

The scale is **per model, not always 25**: 25 in 195 files, 200 in 31, 100 in 29, 50 in 10, and a few others
(500, 75, 400, 250, 28, 1000). Vertex order is not preserved between the PC `.p` files and the PS1 blocks.

Names: 163 of the 287 PS1 overlays have a PC folder or file of the same name; 124 do not (among them
sennkoku, fire and death), and 103 PC folder names match no overlay.

One oddity: the PC release's own skull for this spell is a different model (its `head.p` has 102 vertices and
none of them equals a source or PS1 vertex). So the PC port did not ship the model whose source it left behind.

## Checking it

The fit is reproduced by one script, standard library only:
`sennkoku_geo_check.py deathlv5.geo SENNKOKU.BIN deathlv5_sk.geo` prints the vertex, face, colour and skeleton
figures above. `lgp_unpack.py` unpacks the PC archive (it handles the same file name in several folders).
