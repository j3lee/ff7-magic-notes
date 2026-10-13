# The PC release's magic.lgp, measured

Source: `data/battle/magic.lgp` of the PC re-release (51,094,486 bytes, 5,252 entries), unpacked with
`lgp_unpack.py` (5,252 files, 50,503,198 bytes; 652 names repeat across folders, so the unpacker keeps the folder
of each entry). Everything here is a count or a byte comparison; "my reading" marks the rest. Nothing from the archive is in this repository.

## 1. Unpacker bug and the archive's layout

The path table is a list of (folder, TOC index, 0-based) rows: 652 tables, 2,450 rows, one per TOC entry whose conflict
field is non-zero (all 2,450 are referenced exactly once). The path of an entry is folder + "/" + its TOC name; the
first version of the unpacker looked for the file name inside the folder string and so lost them. Fixed;
`--self-test` now builds a three-way collision (`01.p` in three folders plus a top-level `01.p`) and a same-path
collision (second entry suffixed `.dup1`). 2,802 entries sit at the top level, 2,450 in folders under
`ff7/data/battle/`.

## 2. Kinds by folder

| folder | files | by kind |
|---|---|---|
| (top level) | 2,802 | `.pNN` 1,044 (36 `xxxdat` bundles, e.g. `deathdat`, `bahamdat`; first word 1 like `.p`), `.tex` 489, `.rsd` 444, `.p` 427, `.s` 220, `.aNN` 79 |
| special | 1,562 | tex 427, s 410, rsd 366, p 359 (113 folders) |
| magic | 247 | tex 81, rsd 72, p 59, s 35 (45 folders) |
| summon | 243 | rsd 78, s 68, p 64, tex 32, lmd 1 (19 folders) |
| limit2 / limit3 / limit | 115 / 94 / 44 | rsd, p, tex, s (+ 3 `.lmd` in limit2) |
| weapon / blue | 98 / 39 | rsd, p, tex, s |
| effect / item | 6 / 2 | s (+1 rsd) |
| all | 5,252 | `.tex` 1,111, `.rsd` 1,088, `.pNN` 1,044, `.p` 1,021, `.s` 806, `.aNN` 79, `.d` 36, `.tNN` 24, `.b` 23, `.lmd` 14, `.geo` 2, `.hrc` 1, `.shp` 1, `.anm` 1, `.script` 1 |

`.rsd` (1,054 of 1,088 start with `@RSD`) are text resource descriptors (`PLY=`, `MAT=`, `GRP=`, `NTEX=`). All 1,021 `.p`
and 1,044 `.pNN` start with the P-file word 1. The Lisp text is in 4 entries: `deathlv5.geo`, `deathlv5_sk.geo`,
`script-1.script` (byte-identical to the files that were sent) and `deathlv5.hrc`, a 147-byte skeleton list (bones
head/none/jaw with lengths 45.797066, 3.3178074, 17.573845, the same numbers as `deathlv5_sk.geo`).

## 3. Names against the 287 PS1 overlays

(`MAGIC-OVERLAYS-OVERLAYS.tsv` at the top of this repository.)
129 overlay names equal a folder name, 64 equal a file stem, 30 both: **163 of 287 overlays** have a same-named folder
or stem in the archive; 124 have none by name (for example `fire`, `death`, `sennkoku`, `aeroga`, `kujata`). 103 folder
names have no overlay of that name (`alexand`, `fenic`, `choco2`, `hardeath`, ...), so the archive's naming is not the
disc's. The file the question started from, `lvl5death`/`deathlv5`, belongs to `SENNKOKU.BIN` by content (see
`SENNKOKU-VS-SCRIPT.md`), not by name: no `sennkoku` entry exists.

## 4. The `.s` files are the PS1 sprite-quad tables

All 806 `.s` files open with the word 0x2023 and a frame count, then frames of {s16, s16 quadCount} followed by
0x14-byte quads (flags, x, y, u, v, tpage, clut, w, uw, h, vh): walking them this way ends exactly at the end of
every file (806 of 806; sizes 32 to 2,040, median 176). That is the `SpriteAnim` layout the shared-code survey finds in
the overlays.
- **760 of 806 are byte-identical to a run inside some overlay**, in 212 overlays (457 files in exactly one
  overlay, the rest in 2 to 8).
- **6 more are identical except the tpage word** (for example `lv5deth.s` against `g_Lv5DeathSpriteModel` in
  LV5DETH.BIN: 8 frames, 16 quads, the only difference is the low byte of tpage, 0x2C in the PC file and 0xAC in the
  overlay, in all 16 quads).
- 40 have no counterpart I could find (`formula1.s`, `lens_1.s`, `exp_1.s`, ...).
- Worked case: `ayasii.s` (956 bytes) is found once in AYASII.BIN at +0x65C4: header {0x2023, 12}, 12 frames with
  4,4,4,4,4,4,4,4,4,4,3,2 quads, first quad flags 0x100, x -32, y -32, u 0, v 0, tpage 0x2C, clut 0x7808, 32x32.
My reading: the PS1 table was the source and the PC release carries it unchanged (with the one tpage edit above).

## 5. The `.p` polygon files against the PS1 model blocks

PC `.p` (P-file: header 0x80, vertex count at +0x0C, float vertices from 0x80). For the 343 `.p` files that sit in a
folder or have a stem named like an overlay, each distinct vertex was tested as `trunc(scale * x)` against the vertices
of the model blocks of that overlay (blocks found with the shared-code survey's validator):
- **281 of 343 files (85 overlays): every distinct vertex equals a PS1 vertex under one scale** (needs at least 8
  vertices; subset test, so a PS1 block may have extra vertices). The scale is not always 25: 25 in 195 files,
  200 in 31, 100 in 29, 50 in 10, 500 in 5, 75 and 400 in 4 each, 250, 28 and 1000 in one each.
- Vertex order is not preserved: `brizad.p` (84 vertices) maps all 84 vertices exactly under `trunc(25 x)`, but
  compared index for index the largest difference is 923 stored units.
- Worked cases: `brizad.p` -> BRIZAD.BIN block at +0x3F0, scale 25, 84 of 84 (84-vertex block); `queir.p` -> scale 28,
  97 of 97; `kien.p` -> scale 25: 99 PC vertices, a 96-vertex block, every distinct PC vertex found in it.
My reading: the PS1 models are exports of the same geometry at a per-model scale, with truncation toward zero as for
`deathlv5` (25 units per foot there); the PC release kept the geometry, in floats.
The skull itself is the exception that proves nothing: the PC archive has `head.p` (102 vertices, 122 polygons) and
`jaw.rsd` at top level, referenced by the `.hrc`'s bone names (my reading), but `head.p` is not the 212-vertex `.geo`
head and none of its points equals a `.geo` or overlay vertex, so the PC release's own skull is a different, smaller
mesh.

## 6. The question that started this

- The PC release holds no script source for the effects. The Lisp text exists in four entries (the geometry, the
  skeleton, the one-frame script and a skeleton list), all for one object, `deathlv5`; the 806 `.s` entries are
  binary sprite-quad tables identical to the PS1 ones, not scripts.
- The one N-World asset left in it shows the model pipeline for that spell: `deathlv5.geo` + `deathlv5_sk.geo`
  reproduce the overlay's 303 vertices, 534 faces, 3 bone lengths, parents and rest rotations by fixed rules
  (`SENNKOKU-VS-SCRIPT.md`, section 2b). It does not show how the effect code was written: its script is one frame
  long and none of the C's numbers is in it.
- Beyond that spell the archive shows a family resemblance, not a pipeline: sprite tables identical to the overlays,
  vertex sets of 281 `.p` files equal to overlay model vertices at a per-model scale.
