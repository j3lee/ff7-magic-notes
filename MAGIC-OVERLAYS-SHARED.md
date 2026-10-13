# What the MAGIC overlays have in common

Measured from the original US disc files (`MAGIC/*.BIN`, 287 files, each checked against the sha1 in the attached
overlay table; `BATTLE.X` for the entry table). Nothing here is read from decompiled C, so it holds whether or not
a function is decompiled. One script and three tables are attached with this document; the script is the only
source of the figures (see Rerun at the bottom). Names are only those upstream already has in its symbol files;
anything else is an address.

## What a maintainer can act on

1. **One program shape.** All 287 overlays load at 0x801B0000, are entered through one 496-entry table in the
   battle executable, and register per-frame functions with `BattleEffectRegister` that work on their own
   `g_BattleEffectSlots[g_BattleEffectCursor]` entry. 175 of them share one 8-instruction entry stub.
2. **Half the functions are copies, but they are the small ones.** 311 families of instruction-identical functions
   cover 47 percent of the functions and 29 percent of the code bytes; sharing each once would remove 22 percent of
   the code, and 71 percent of the code is unique to one overlay.
3. **The overlay is its data.** Code is 3.9 percent of the 45.5 MB. Of the data, 45 percent is TIM images and 48
   percent is zero fill, mostly one 0x18000-byte buffer area in 158 overlays; of the 7 percent left, 69 percent is
   model geometry and sprite-quad tables in formats upstream already types (section 5); the PC release stores the same
   tables and geometry as separate named files (section 6).

## 1. Scale

| | |
|---|---|
| overlays / functions | 287 / 3,959 (functions per overlay: 2 to 111, median 11) |
| code bytes per overlay | 448 (gattai) to 60,156 (knights), median 3,984 |
| data bytes per overlay | 0 (gattai) to 273,728, median 152,276 |
| load address | 0x801B0000 for all 287 |
| function split | start of file, `jal` targets, and the word after a `jr ra` no earlier branch jumps past; code range from the overlay table. Same function count as a local import of all 287 overlays as assembly includes in 285 of 287 overlays (3,959 against 3,957 functions) |

## 2. Shared code (`MAGIC-OVERLAYS-FAMILIES.tsv`: one row per family)

Families by number of overlays: 167 are in exactly 2, 144 in 3 or more, 29 in 10 or more, 17 in 20 or more. Inside
one overlay the median share of code that sits in a family is 25.3 percent; 73 overlays have at least half.
Near copies (at least 20 instructions, 85 percent alike in another overlay, not in an exact family) add 100 groups,
262 functions, 154,712 bytes: with them 2,130 functions (53.8 percent) and 666,184 bytes (37.6 percent).

| family | overlays | instr. | what the bytes show | what varies between copies |
|---|---|---|---|---|
| F022 | 175 | 8 | entry stub: frame, one `jal` into the overlay, return | the jal target |
| F007 | 95 | 27 | effect callback: reads its slot, forms a work-area pointer from slot+2, flips a bit, frees the slot on a battle-state condition | 2 address halves, 2 constants |
| F017 | 76 | 21 | picks one of two buffers by a battle flag, frees the slot on a condition | 4 address halves, 4 constants |
| F005, F010, F011, F012 | 38 (one set) | 95, 57, 55, 55 | rotation and vector helpers: `rsin`/`rcos`; `VectorNormal`, `SquareRoot12`, `OuterProduct12`, `ratan2` | nothing: byte-identical copies |
| F008 | 22 | 107 | calls `BattleGetPartPosition`, reads two battle-state values | nothing |
| F001 | 8 | 1,037 | camera and part geometry: `SquareRoot0`, `VectorNormalS`, `ApplyRotMatrix`, `SetRotMatrix`, `SetTransMatrix`, `RotTrans`, `BattleGetPartPosition`; reads `g_BattleCameraTarget`, `g_BattleCameraPos` | 64 address halves (its own data and bss), 64 constants |
| F002, F003, F004 | 8 | 688, 650, 452 | self-contained: no external call, no global | only internal jump targets (9, 1, 2 positions) |

Families sit in groups: the four 38-overlay families are the same 38 overlays; F001 to F004 are two sets of 8; ten
overlays (club1, club2, dia1, dia2, heart1 and others) share six more. The five routines called from the most overlay
functions are `BattleEffectRegister` (1,153 functions), `SetTransMatrix` (912), `SetRotMatrix` (911),
`CompMatrix` (581) and `rand` (574).

## 3. The skeleton, in order

| step | what the bytes show | count |
|---|---|---|
| battle code calls an entry address from the table | +0x0 or +0x54 in most; 123 addresses in all | 496 table entries |
| entry stub | frame, `jal init`, return; at +0x0 or after one small callback | 175 overlays |
| init | calls `BattleEffectRegister` once or more, passing the address of a per-frame function | 287 overlays |
| per-frame functions | read `g_BattleEffectSlots[g_BattleEffectCursor]`, advance state in the 0x20-byte slot | 2,049 functions |
| end | store -1 at slot+0 | 2,041 functions |

No separate teardown routine shows up; the free store is the end of an effect. Functions whose address is taken
inside the overlay: 1 to 70 per overlay (median 7).

## 4. What a shared header would hold (sketch only, not a patch)

```c
// src/magic/shared.h  (sketch)
#define MAGIC_ENTRY(init) void MagicEntry(void) { init(); }        // F022: 175 overlays
#define MAGIC_SLOT()      (&g_BattleEffectSlots[g_BattleEffectCursor])   // 2,049 functions
#define MAGIC_FREE(slot)  ((slot)->state = -1)                      // 2,041 functions
void MagicSlotCallbackA(MagicWork* work, void* bufBase, s32 k);     // F007: 95 overlays, 2 data addresses + 2 constants
void MagicBufferSelect(void* bufA, void* bufB);                     // F017: 76 overlays
void MagicVecHelpers(...);                                          // F005/F010/F011/F012: 38 overlays, identical
// each overlay keeps: init and its registered callbacks, its tables, its textures
```

What each overlay would still own: 71 percent of its code bytes (2,091 functions in all, 306 of 10 to 49
instructions, 1,334 of 50 to 199, 446 of 200 or more) and all of its data.

## 5. Data and assets

Data bytes: 43,743,259. Three parts:

| part | bytes | share |
|---|---|---|
| PSX TIM images (283, in 261 overlays; 270 distinct, 25 identical to another overlay's) | 19,678,032 | 45.0 % |
| zero fill outside the images | 20,972,620 | 47.9 % |
| everything else (non-zero, not an image) | 3,092,607 | 7.1 % |

**Everything else, by what it is** (found in the bytes by layout, then checked against the code that addresses it;
the layouts are the ones upstream already types in `battle.h`):

| kind | bytes | share | overlays | identified by | confidence |
|---|---|---|---|---|---|
| model blocks, start address built by code or stored as a pointer | 1,205,493 | 39.0 % | 187 | layout in the bytes, the code that addresses it, and one model matched to source (section 6) | high |
| model blocks, layout only | 850,999 | 27.5 % | 34 | layout in the bytes; no reader found | medium |
| sprite-quad tables (upstream `SpriteAnim`) | 91,247 | 2.9 % | 194 | layout in the bytes; 686 of 725 start at a built or stored address | high |
| vertex-like arrays, no header | 200,567 | 6.5 % | 41 | statistics of the bytes only | low |
| unknown, address built by code | 289,815 | 9.4 % | 134 | not identified | unknown |
| unknown, no reference found | 436,082 | 14.1 % | 141 | not identified | unknown |
| unknown, pointed to from data | 17,594 | 0.6 % | 14 | not identified | unknown |
| short runs under 64 bytes | 810 | 0.0 % | 39 | not classified | unknown |

Reading the table:
- *Sprite-quad tables* are upstream's `SpriteAnim`: a header of two words (the first is 0x2023 in all 109 runs
  that open with it), then frames of `{s16, s16 quadCount}` followed by 0x14-byte `SpriteQuad`s (flags, x, y, u, v,
  tpage, clut, w, uw, h, vh). They are read by the routine upstream types as taking a `SpriteRenderDesc`
  (`func_800D4D90`). Accepted only when tpage and clut fall in the ranges seen in valid tables; not checked against
  the overlay's own TIM images.
- *Model blocks* follow the layout `func_800D29D4` reads (`ModelRenderDesc.model`): a word giving the offset of the
  face lists, an array of 8-byte vertices (s16 x, y, z, 0), then four lists, each a count followed by fixed-size
  records that refer to vertices by byte offset (index x 8): 16-byte textured triangles; a 20-byte list (empty in the
  one model decoded against source); 20-byte gouraud triangles (colour per vertex, command byte 0x30); 24-byte
  gouraud quads (command byte 0x38). The meanings come from section 6's model, where all 534 faces were matched; the
  detector itself uses only the sizes. A block is accepted when the vertex padding is zero, the first indices are
  multiples of 8 inside the vertex array and the four counts chain to a position inside the run. "Address taken"
  means the block's start is built by code (`lui` plus low half) or stored as a pointer in the overlay's data (879
  blocks; 114 of the code references are followed by a call to `func_800D29D4`). "Layout only" blocks fit the
  layout but nothing addresses their start: reached by offset from another block, or false positives (not
  separated).
- *Vertex-like arrays* are runs where 70 percent or more of the 8-byte records have a zero fourth halfword and a
  non-zero x, y or z, with no header word: probably vertex data of a model whose header was not recognised.
- *Other* is what has no recognised layout: 744,301 bytes (24.1 %) in total with the short runs.

**Zero fill** (19,747,023 bytes in runs of 64 or more; 1,225,597 more zero bytes sit inside non-zero data):

| zero runs | bytes | overlays | runs |
|---|---|---|---|
| two 0xC000-byte buffers; code builds some other address inside | 9,180,787 | 93 | 93 |
| two 0xC000-byte buffers; code builds both bases | 6,343,945 | 64 | 64 |
| other run of 16 KiB or more; code builds an address inside | 4,007,365 | 42 | 42 |
| other run of 16 KiB or more; no address inside built by code | 100,320 | 2 | 2 |
| two 0xC000-byte buffers; no address inside built by code | 98,314 | 1 | 1 |
| run under 16 KiB (64 bytes or more) | 16,292 | 16 | 80 |

158 overlays have a zero run of 0x18000 to 0x18FFF bytes (two 0xC000-byte buffers and a short tail). In 64 of them
code builds both buffer base addresses; in 93 it builds some other address inside the run; in 1 nothing addresses it.
Code that builds both bases is the shape of a double buffer, selected by a flag (family F017, 76 overlays); the
bytes show zeros stored in the file, not what the game puts there at run time.

Unknown: what the 744,301 unclassified non-zero bytes are; what the vertex-like arrays belong to; whether the "layout
only" blocks are all models; how a magic id maps to an overlay file.

## 6. The same data in the PC release

Source: our measurements of the PC release's `data/battle/magic.lgp` (5,252 entries) against these overlays, made
separately from the script attached here and not reprinted by it; each figure is a byte or value comparison. This is
asset correspondence only.

| the PC release stores, as named files | files | against the PS1 overlays |
|---|---|---|
| `.s` sprite-frame tables | 806 | all 806 walk as `SpriteAnim` to the exact end of the file; 760 are byte-identical to a table inside an overlay (212 overlays); 6 more differ in one tpage byte; 40 not found |
| `.p` models (343 named like an overlay) | 281 | every distinct vertex equals trunc(scale x a vertex of that overlay's model block), 85 overlays; the scale is per model: 25 in 195 files, 200 in 31, 100 in 29, 50 in 10, 500 in 5, five others in 11 |
| overlay names | 163 of 287 overlays | a same-named folder or file in the archive; 124 have none (for example `fire`, `death`, `aeroga`) |

The PC `.s` tables are the overlays' sprite-quad tables unchanged, and the `.p` vertex sets are the overlays' model
vertices at a per-model scale (the vertex order is not kept).

One object is a source asset: three Lisp text files (geometry, skeleton, a one-frame script) for `deathlv5`, which
halkun pointed at. They match the model block of `SENNKOKU.BIN` point for point: all 303 vertices (x agrees for 302,
one is off by a unit; y and z for all 303 after the bone's rest rotation), all 534 faces, the three bone lengths and the rest rotations
follow from the files by one rule, 25 stored units per foot, truncated. That match is what decoded the face lists in
section 5.

Limit: this shows that the PS1 model blocks and sprite tables correspond to assets the PC release still carries. It says nothing about how the effect code was written; the PC release holds no script source for the
effects (the Lisp text exists for this one object only, and its script is one frame long).

## 7. Compiler

All 287 overlays use `cc1-psx-26` (GCC 2.6.3): 283 with assembler 2.21 (`PSYQ=3.3`), 4 with 2.34 (`PSYQ=3.5`). The
setting is confirmed for 272 overlays by at least one function compiling to the original bytes in a local import;
unconfirmed for the other 15.

## Not measured

Names and purposes beyond the callee and data evidence above; what the unclassified data is; near-copy thresholds
other than 85 percent.

## Rerun

Attached: `magic_shared.py`, `MAGIC-OVERLAYS-OVERLAYS.tsv` (per overlay: file, load address, sha1, where the code
starts and ends), `MAGIC-OVERLAYS-FAMILIES.tsv`, `MAGIC-OVERLAYS-NUMBERS.json`. The script uses only Python 3 and its
standard library and takes its paths as arguments (`--help`).

```
python3 magic_shared.py --magic <checkout>/disks/us/MAGIC --battle <checkout>/disks/us/BATTLE/BATTLE.X.dec --out out/
```

It needs the 287 `.BIN` files of the US disc in that folder and the attached overlay table (found next to the script,
or `--table FILE`); `--battle` is the battle executable for the entry table (that section is skipped without it);
`--symbols <checkout>` names addresses from its `config/symbols.*.txt` (addresses are printed without it). It prints
every number above and writes `MAGIC-OVERLAYS-NUMBERS.json` and `MAGIC-OVERLAYS-FAMILIES.tsv` into `--out`. The
compiler section needs `--src <tree with src/magic>`, which only a local import has; it is skipped otherwise.
