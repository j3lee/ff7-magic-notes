# A data model of the MAGIC overlays (FF7, PS1, US)

**Coverage: the parser places 98.89 % of the 45,515,711 bytes of the 287 overlays** (code, a walked data format, or
zero fill). Of the 23,991,909 bytes of data that are not zero fill, **97.90 % are walked by a format of this
model**; 99.27 % with the vector arrays that are typed by shape only. 174,325 bytes (0.38 %) are not placed and are
listed range by range in `UNPLACED.tsv`.

"Walked" means: a block counts only when the parser followed the layout to its last byte with every check passing
(lengths that add up, every vertex reference inside the vertex array, a bit stream that ends on the stated size).
Nothing is counted because of where it sits. Every figure here is printed by `magic_data.py` (`RUN.txt` is the
last run); names of fields come from a reader in the battle executable or from the PC release's counterpart file,
and the evidence column says which. Where neither exists the field is `unk` and its measured values are given.

Status: a measurement and a proposal for discussion. Nothing here is a patch.

## 1. Map: an overlay consists of ...

| part | blocks | bytes | share | section |
|---|---|---|---|---|
| code (range from the overlay table) | 287 | 1,772,452 | 3.89 % | 2 |
| TIM images | 283 in 261 overlays | 19,678,032 | 43.23 % | 3 |
| zero fill: runs of 0x18000 bytes or more (primitive double buffer and what follows it) | 175 | 17,706,368 | 38.90 % | 4 |
| zero fill: other runs of 16 bytes or more, and padding | 477 | 2,044,982 | 4.49 % | 4 |
| model blocks addressed on their own | 1,009 in 207 overlays | 2,024,004 | 4.45 % | 5 |
| skeleton containers: header, bone table, bone meshes, script block, animations, empty TIM | 23 containers, 579 meshes, 54 animations | 1,293,328 | 2.84 % | 6, 7, 8 |
| animation packs (limit-break overlays): offset table, records, placeholders | 43 packs, 198 records | 304,388 | 0.67 % | 9 |
| one animation record outside a container | 1 | 3,112 | 0.01 % | 8 |
| sprite tables | 784 in 218 overlays | 169,068 | 0.37 % | 10 |
| descriptors and pointer tables that point at the above | 1,053 | 16,684 | 0.04 % | 11 |
| vector arrays (shape only, no walked format) | 107 in 20 overlays | 328,968 | 0.72 % | 12 |
| not placed, code addresses it (the overlay's own variables and tables) | 627 ranges | 55,279 | 0.12 % | 13 |
| not placed, nothing addresses it | 318 ranges | 119,046 | 0.26 % | 13 |

How things hang together in one overlay:

```
battle executable --(entry table, 496 entries)--> overlay entry function
  entry function --> BattleEffectRegister(per-frame function)      effect slot, 0x20 bytes      (section 14)
                 --> BattleSetLoadTimToVram(TIM)                   TIM -> VRAM rectangle        (section 3)
                 --> returns EffectModelHeader*                    skeleton container           (section 6)
  per-frame function --> BattleDrawModel(ModelRenderDesc)          model block                  (section 5)
                     --> BattleDrawSpriteQuads(SpriteRenderDesc)   sprite table                 (section 10)
                     --> writes GPU packets into prim buffer [g_dbIndex]   zero run             (section 4)
```

Four overlays were read end to end before the parser was run over all: `sennkoku` (skeleton container, matched to
its N-World source and its PC bundle), `ayasii` (one TIM, one sprite table, one descriptor, buffers: 100 % placed),
`lv5deth` (models, sprite, 8-bit TIM: 100 % placed) and the summon `tupon` (48-bone container, 7 animations, 23
models and sprites with PC names; 843 bytes left, all code-addressed).

## 2. The overlay file

| what | value | evidence | confidence |
|---|---|---|---|
| load address | 0x801B0000 for all 287 | overlay table (`overlays.tsv`, from the build configuration) | high |
| code | one range per overlay; starts at file offset 0 in 239, later in 48 | overlay table | high |
| before the code (48 overlays) | 8 to 224 bytes; in 20 of them every word is the address of a function of the overlay | bytes | medium |
| data | everything after the code; there is no header, no section table and no relocation | bytes | high |
| bss | none outside the file for 281 overlays: the work areas are zero bytes stored in the file (section 4) | overlay table, bytes | high |
| entry | the battle executable calls an address from one table of 496 entries; the entry function returns the address of the skeleton container or 0 | `MAGIC-OVERLAYS-SHARED.md` section 3; `battle1.c` (`D_800F57D0 = func_801B0040(...)`) | high |

Finding instances: nothing in the file says where a block is. Every block is found from an address that code
builds (`lui` plus low half) or that a data word holds; `BLOCKS.tsv` records for each block which of the two
(`found_by`: `code`, `pointer`, or `layout` when only the layout check found it).

Unknown: how a magic id selects the overlay file (it is in the battle executable, not in the overlay).

## 3. TIM images and where they go in VRAM

Standard PSX TIM: id 0x10, flag word, optional CLUT block, pixel block; each block is `u32 length, u16 x, y, w, h`
and `length - 12` bytes. The parser accepts a TIM only when both lengths equal `12 + 2 * w * h`.

| field | meaning | evidence |
|---|---|---|
| flag bits 0-1 | 0 = 4-bit (258 images), 1 = 8-bit (25) | TIM format |
| CLUT block x, y | VRAM position of the palette: (128, 480) in 229, (768, 255) in 24, (128, 481..497) in 28, 2 others | bytes |
| CLUT block w, h | 16 or 256 colours wide, h palettes | bytes |
| pixel block x, y | VRAM position of the image: (768, 0) in 251, (832 / 896 / 960, 0) in 24, others in 8 | bytes |

Upload: `BattleSetLoadTimToVram(tim, 0, 0, 0)` (`battle2.c`: it calls `BattleSetLoadClutToVram` and
`BattleSetLoadTextureToVram`). 272 of the 283 TIMs start at an address code builds; for 215 the next call after
that reference is `BattleSetLoadTimToVram`. The other arguments are zero in the calls read, so the rectangle is the
one in the TIM header. For the TIM a skeleton container ends with, the engine makes the call itself
(`BattleLoadEffectModel`: `offsets[numOffsets - 1]`).

The rectangle links the image to its users: page (768, 0) in 4-bit mode with blending mode 1 is tpage 0x2C, and
palette (128, 480) is clut 0x7808; these are the tpage and clut values in the sprite quads. Checked: in 693 of 784
sprite tables every clut lies inside the CLUT rectangle of a TIM of the same overlay, and in 727 every tpage
overlaps a pixel rectangle of a TIM of the same overlay. The rest use pages of textures loaded by something else
(not resolved).

Confidence: high. Unknown: for the 11 TIMs found by layout only, who uploads them.

## 4. Zero fill and the primitive double buffer

| kind | blocks | bytes |
|---|---|---|
| zero runs of 0x18000 bytes or more | 175 overlays | 17,706,368 |
| other zero runs of 16 bytes or more | 412 | 2,044,586 |
| padding to a word boundary or between blocks | 65 | 396 |

The 0x18000 run is two buffers of 0xC000 bytes followed by a few words of variables. Reader, in the decompiled
`sennkoku.c`: `g_SennkokuBufferPtr = g_dbIndex == 0 ? g_SennkokuPrimBuffer0 : g_SennkokuPrimBuffer1;` and the
drawing calls receive that pointer as their `prim` argument (`BattleDrawModel(desc, ot, otLen, prim)` returns the
advanced pointer). So each half is the GPU packet buffer for one of the two display buffers: the routine draws
into the half that is not on screen. The same selection function is instruction-identical in 76 overlays (family
F017 of the shared-code survey). In `sennkoku` and `ayasii` code builds the addresses run+0, run+0xC000 and
run+0x18000 onward (the variables).

What is stored: zeros. The file carries them because the overlay has no bss.

Confidence: high for the 64 overlays where code builds both buffer bases and for the two read in C; medium for the
other runs of this size (same size, the addresses built are elsewhere inside the run). Unknown: the meaning of the
other zero runs (work areas of the overlay's own code).

## 5. Model block (`ModelRenderDesc.model`)

Reader: `BattleDrawModel` (0x800D29D4, still assembly: `asm/us/battle/nonmatchings/battle2/BattleDrawModel.s`).
Every offset below is one that routine loads from. Decoded against source: the two meshes of `sennkoku` match
`deathlv5.geo` vertex for vertex and face for face (`DEATHLV5-FINDINGS.md`).

| offset | type | field | meaning | evidence |
|---|---|---|---|---|
| 0x00 | u32 | vertexBytes | size of the vertex array in bytes; the face lists start at 4 + vertexBytes | reader (`lw 0(a0)`, added to the vertex base) |
| 0x04 | SVECTOR[vertexBytes / 8] | vertices | s16 x, y, z, pad 0 | reader (loaded into the GTE as vertex words); source: stored = trunc(25 x source value) |
| then | u16 | texTriCount | | reader (`lh`) |
| +2 | u16 | texTriTpage | masked with 0x19F and added to the descriptor's tpage, unless the descriptor has flag 0x40 | reader. This is "the constant 44": 0x2C in 200 blocks, 0x20 in 425, 0x2D / 0x2E / 0x2F in 300 |
| | ModelTexTri[texTriCount] | | 0x10 bytes each | reader |
| then | u32 | texQuadCount | read as a whole word | reader (`lw`) |
| | ModelTexQuad[texQuadCount] | | 0x14 bytes each | reader |
| then | u16 | colTriCount | | reader (`lh`) |
| +2 | u16 | unk | not read; 0 in all 1,588 blocks | bytes |
| | ModelColTri[colTriCount] | | 0x14 bytes each | reader |
| then | u32 | colQuadCount | read as a whole word | reader (`lw`) |
| | ModelColQuad[colQuadCount] | | 0x18 bytes each | reader |

Vertex references in all four records are byte offsets into the vertex array (index x 8): the reader adds them to
the vertex base without scaling.

| record | offset | type | field | meaning | evidence |
|---|---|---|---|---|---|
| ModelTexTri (0x10) | 0x0 | u16[3] | vertex | byte offsets of the corners | reader |
| | 0x6 | u8 | shade | under descriptor flag 0x80 (depth cue): grey level of the packet colour | reader (`andi 0xFF`, copied to r, g, b) |
| | 0x7 | u8 | page | under flag 0x40: per-face tpage (masked 0x19F, added to the descriptor's); under flag 0x100: ORed into the top byte of the packet colour word | reader |
| | 0x8 | u8, u8 | u0, v0 | first texture coordinate | reader (word stored to packet +0xC) |
| | 0xA | u16 | clut | added to descriptor clut | reader (same word; descriptor clut << 16 is added) |
| | 0xC | u8, u8 | u1, v1 | stored to packet +0x14 | reader |
| | 0xE | u8, u8 | u2, v2 | stored to packet +0x1C | reader |
| ModelTexQuad (0x14) | 0x0 | u16[4] | vertex | | reader (fourth through `rtps`) |
| | 0x8 | u8, u8, u16 | u0, v0, clut | | reader |
| | 0xC | u8, u8 x 3 | u1, v1 .. u3, v3 | packet +0x14, +0x1C, +0x24 | reader |
| | 0x12 | u8, u8 | shade, page | as in the triangle | reader |
| ModelColTri (0x14) | 0x0 | u16[3] | vertex | | reader |
| | 0x6 | u16 | unk | not read | reader does not load it |
| | 0x8 | CVECTOR[3] | color | r, g, b and the GPU command in the first (0x30 in the decoded model) | reader (three words to packet +4, +0xC, +0x14); source: about 0.74 of the part's diffuse colour |
| ModelColQuad (0x18) | 0x0 | u16[4] | vertex | | reader |
| | 0x8 | CVECTOR[4] | color | command 0x38 in the first | reader |

The uv halfwords get the descriptor's `uvOffset` added. Packets written: POLY_FT3 (tag 0x07 words, command 0x24),
POLY_FT4 (0x09, 0x2C), POLY_G3 (0x06), POLY_G4 (0x08).

How instances are found: 375 blocks start at an address code builds, 609 at an address a data word holds (inside
a `ModelRenderDesc`, section 11, or a pointer table), 25 by layout only (74,024 bytes: probably reached by offset
from a neighbour; not separated from false positives). For 88 code references the next call is `BattleDrawModel`.

PC counterpart: `.p` files. For 823 of 1,021 `.p` files (at least 8 distinct vertices) every vertex equals
trunc(scale x) of a vertex of one PS1 block, at one scale per file (25 most often); the order differs. Names per
block are in `OVERLAY-ASSETS.tsv`.

Confidence: high (reader, source and PC agree). Unknown: `ModelColTri` +0x6 and the second halfword of the third
list header; why 22 textured triangles of the decoded model repeat coloured ones.

## 6. Skeleton container (`EffectModelHeader`)

The overlay's entry function returns its address; the engine keeps it in `D_800F57D0`. Readers:
`BattleLoadEffectModel`, `BattleGetModelBoneNumAndInitBones` (`battle1.c`, both in C). 23 overlays have one.

| offset | type | field | meaning | evidence |
|---|---|---|---|---|
| 0x00 | s32 | numOffsets | 4 to 10 | reader (`offsets[numOffsets - 1]`) |
| 0x04 | s32[numOffsets] | offsets | from the start of the container | reader |
| | | offsets[0] | skeleton section; always 4 + 4 x numOffsets | reader (`EFFECT_MODEL_SKELETON`) |
| | | offsets[1] | script block (section 7); the loader turns it into an address | reader |
| | | offsets[2 .. numOffsets - 2] | animation records (section 8), numOffsets - 3 of them | reader (`&offsets[2]` is passed as the animation table) |
| | | offsets[numOffsets - 1] | a TIM, uploaded by the loader | reader (`BattleSetLoadTimToVram`) |

The last TIM is a real texture in 10 containers and an empty one (CLUT block, pixel block of width 0) in 13.

Skeleton section:

| offset | type | field | meaning | evidence |
|---|---|---|---|---|
| 0x0 | u16 | boneCountMinus1 | bone count = value + 1 (4 to 49) | reader (`*count = *data + 1`) |
| 0x2 | u16 | unk | 0 in all 23 | bytes |
| 0x4 | BattleModelBoneEntry[count] | bones | entry 0 is the root: all zero | reader |
| then | model blocks | | one per bone that has a mesh, layout of section 5 | reader, source |

Bone entry (8 bytes, upstream's `BattleModelBoneEntry` in `battle_private.h`; the container header is upstream's
`EffectModelHeader` in `src/magic/magic.h`):

| offset | type | field | meaning | evidence |
|---|---|---|---|---|
| 0x0 | s16 | parent | index of the parent bone | reader (parent matrix lookup); source: parents 0, 0, 2 equal the `.geo` segment list |
| 0x2 | u16 | z (upstream's name; the PC file calls it the length) | minus the bone length, as a signed value; the child's translation along z | reader (`trans.vz = bones[parent].z`); source: -trunc(25 x `:normal-length`); PC `.d`: the same value as a float |
| 0x4 | s32 | modelOffset | 0 = no mesh; else mesh = section + 4 + (value & 0x7FFFFFFF) - 4; a negative value sets `boneFlags[i] = 1` | reader |

PC counterpart (the "xxxdat" bundles, 36 of them): `.d` = 52-byte header with the bone count at +0x0C, then 12
bytes per bone (s32 parent, -1 for the root; float length; u32 has-mesh). For 22 of 36 `.d` files the bone count
and every length equal a PS1 container's. `.pNN` = the mesh of bone NN + 1: all 374 vertices of `5dethdat.p00`
are vertices of `sennkoku`'s first mesh at scale 1; 526 of 1,044 `.pNN` files match a PS1 block this way.

Confidence: high. Unknown: what `boneFlags` = 1 changes (no container sets the bit: 0 flagged bones in 23);
the second halfword of the section.

## 7. Script block

`offsets[1]` of the container. Reader: `BattleLoadEffectModel` adds the block's address to its first 8 words;
`BattleExecuteUnitAnimScript` (assembly) takes `table[model.animScriptId]` as the script pointer.

| offset | type | field | meaning | evidence |
|---|---|---|---|---|
| 0x00 | s32[8] | scriptOffsets | from the start of the block; all eight are 0x38 in all 23 blocks | reader (relocation loop of 8; table lookup) |
| 0x20 | u8[24] | unk | two value sets only: `64 00 00 08 00 08 00 ...` in the 7 spell containers, `F4 01 00 10 00 10 00 ...` in the 16 summon containers; bytes 0x30..0x33 are 3 in all | bytes; no reader found |
| 0x38 | u8[] | script | byte code, padded to a word; block size 60 to 80 | reader |

Script bytes: a value below 0x8E is the index of an animation to play (reader: the interpreter subtracts 0x8E and
dispatches the 0x72 values above through a jump table; below it the byte is an animation index). Checked: in the
15 scripts that consist only of indices and the bytes C9, C1, F1, every index is below the container's animation
count. Example, `tupon`: `00 01 02 03 04 05 C9 06 C1` (animations 0 to 5, then 6 in a loop). Of the other 8 scripts, 7 are
`E7 00 E1 F4 01 F3 E7 01 C9 00 C1` (the 7 spell containers) and one (`riva`) ends in `FE C0`. Opcode meanings are documented by the community for the same
interpreter (C9 = jump target, C1 = jump back to it, F4 nn = set wait, F3 = wait); they were not re-derived here.

PC counterpart: `.b`. All 23 `.b` files are byte-identical to a PS1 script block (`5dethdat.b` = `sennkoku`'s 68
bytes).

Confidence: high for the offsets and the index rule; the opcodes are third-party. Unknown: the 24 bytes at 0x20.

## 8. Animation record

Reader: `BattleExecuteUnitAnimScript` and its helpers (assembly). The layout below was confirmed by decoding: for
all 253 records the bit stream, decoded with the container's bone count, ends in the last byte the header's size
gives.

| offset | type | field | meaning | evidence |
|---|---|---|---|---|
| 0x0 | u16 | frames | number of frames | decode; PC header |
| 0x2 | u16 | size | bytes of bit stream that follow the 5-byte header | decode lands on it; PC header |
| 0x4 | u8 | key | lost precision bits; an angle is stored in 12 - key bits. 0 in all 253 | decode |
| 0x5 | bit stream | | most significant bit first; the record is padded to a word | decode |

Bit stream:

| part | bits | meaning |
|---|---|---|
| frame 0, root offset | 3 x 16 | s16 x, y, z |
| frame 0, per bone | 3 x (12 - key) | rotation x, y, z, shifted left by key; 4096 = a full turn |
| later frames, each offset | 1 + 7 or 1 + 16 | flag 0: 7-bit signed delta; flag 1: 16-bit signed delta |
| later frames, each angle | 1 | 0: unchanged |
| | + 3 | length code n |
| | + n | n = 0: delta -1; n = 1..6: n-bit signed value v, delta = v - 2^(n-1) if v < 0 else v + 2^(n-1); n = 7: (12 - key)-bit delta. Deltas are shifted left by key |

Example, `sennkoku`: 44 frames, 4 bones, 257 bytes; frame 0 root offset (0, -587, 118), bone angles
(-182, -2048, -2048), (690, 0, 0), (-57, 0, 0).

PC counterpart: `.aNN` = u32 count, then per animation u32 bones, u32 frames, u32 size and `size` bytes that are
the PS1 record. 249 of 266 PC records are byte-identical to a PS1 record; `5dethdat.a00` is (1; 4, 44, 264;
`sennkoku`'s record). The PC header is where the names `frames` and `size` come from, and its `bones` field equals
the bone count the decode needs.

One record sits outside a container: `tupon` +0x284B4 (30 frames, 3,104 bytes), at an address code builds.

Confidence: high. Unknown: which bone axis each angle turns (not needed to walk the data).

## 9. Animation pack (limit-break overlays)

43 overlays hold a table of offsets to animation records with no skeleton: the animations belong to a model that
is already loaded (the player character).

| offset | type | field | meaning | evidence |
|---|---|---|---|---|
| 0x00 | u32 | count | 16 in 41 packs, 17 in 2 | bytes |
| 0x04 | u32[count] | offsets | from the start of the pack; first = 4 + 4 x count | bytes |
| each | animation record or `30 1A 00 00` | | section 8, or a 4-byte placeholder (492 of them) | decode |

The first half of the records decode with one bone count per pack (23, 24, 30, 32, 33 or 47), the second half
with a bone count of 1. The bone count is not stored; the parser takes the one count for which every record ends
on its stated size.

Evidence: decode only (198 records land on their size); all 43 packs start at an address code builds. The PC
release has the same split: its animation files hold body animations and then one-bone animations.
Confidence: medium-high for the layout, **no reader was read**: the name "pack", the reading of the second half
as weapon animations and the owner of the bone counts are not established.

## 10. Sprite table (upstream `SpriteAnim`, `SpriteFrame`, `SpriteQuad`)

Reader: `BattleDrawSpriteQuads` (`func_800D4D90`), typed upstream in `battle.h`.

| offset | type | field | meaning | evidence |
|---|---|---|---|---|
| 0x0 | s32 | unk0 | 0x2023 in all 784 tables and all 806 PC files | bytes |
| 0x4 | s32 | frameCount | 1 to 20 (1 to 100 quads per table) | upstream type; PC files end exactly when walked this way |
| 0x8 | SpriteFrame[] | frames | `s16 unk0, s16 quadCount`, then quadCount quads | upstream type |
| quad 0x00 | u32 | flags | `SpriteQuadFlags` (flip u, flip v, semi-transparent, texture size) | upstream type |
| 0x04 | s16, s16 | x, y | | upstream type |
| 0x08 | u16, u16 | u, v | | upstream type |
| 0x0C | u16 | tpage | texture page; links to a TIM's pixel rectangle (section 3) | upstream type; TIM check |
| 0x0E | u16 | clut | links to a TIM's CLUT rectangle | upstream type; TIM check |
| 0x10 | u8 x 4 | w, uw, h, vh | | upstream type |

How found: 51 at an address code builds, 720 at an address a data word holds (a `SpriteRenderDesc` or a pointer
table), 13 by layout with the 0x2023 word.

PC counterpart: `.s`. 764 of 806 PC files are identical to a PS1 table (or identical but for the tpage field);
`ayasii.s` is `ayasii` +0x65C4.

Confidence: high. Unknown: `unk0` of the table and of the frame.

## 11. Descriptors and pointer tables

| kind | size | found | layout | evidence |
|---|---|---|---|---|
| `ModelRenderDesc` | 0x10 | 369 in 143 overlays | `s32* model; s32 flags; u16 uvOffset; s16 color; s16 tpage; s16 clut` | upstream `battle.h`; accepted when the first word is the address of a walked model block and flags < 0x200. Flag values seen: 0xA8 (127), 0x88 (85), 0x00 (43), 0x80 (37), 0x08 (25), 0x28 (23), 10 others |
| `SpriteRenderDesc` | 0xC | 486 in 212 overlays | `SpriteAnim* frames; CVECTOR color; u16 frameIndex; s16 clutBias` | upstream `battle.h`; accepted when the first word is the address of a walked sprite table and the colour's code byte is 0 or 0x2C..0x2F |
| pointer table | 4 x n | 198 in 117 overlays | consecutive words, each the address of a walked block or of a function | bytes |

Confidence: high for the two descriptors (the fields are upstream's), medium for the pointer tables (what indexes
each is in the overlay's code).

## 12. Vector arrays (shape only)

107 runs, 328,968 bytes, in 20 overlays: 8-byte records `s16 x, y, z, 0` starting at an address that code builds
or a data word holds, with no header. In `alex` ten arrays of 887 records each are listed in one pointer table and
whose first records differ only in y; two references are followed by a call to `gteMIMefunc` (vertex interpolation). So some are
key shapes for interpolated models, but the reader of each is in the overlay's own code and was not read.
Counted separately from the walked formats. Confidence: low.

## 13. Not placed

| class | ranges | bytes | what it is |
|---|---|---|---|
| code addresses it | 627 | 55,279 | variables and tables of the overlay's own functions (`sennkoku`: 189 bytes = the spin delay table and state words named in `sennkoku.c`). No shared format; the decompiled C is the description |
| nothing addresses it | 318 | 119,046 | largest: `knights` 91,657 (runs of 4-bit pixels with no TIM header), `siva` 16,210, `sting` 13,896 |

`UNPLACED.tsv` lists every range (overlay, start, end, bytes, class, number of code references).
47 overlays have nothing unplaced.

## 14. The effect slot

`g_BattleEffectSlots[100]`, 0x20 bytes each (`battle_private.h`: `BattleEffectSlot`, a union). It is run-time
state, not data in the file; it is here because the per-frame functions of every overlay work on it.

| offset | type | field | meaning | evidence |
|---|---|---|---|---|
| 0x00 | s16 | state | -1 frees the slot | 2,041 overlay functions store -1 here before returning (shared-code survey); `MagicAnimationData.TargetCursor` "-1 retires the slot" |
| 0x02 | s16 | frame | counts frames | the engine's own slot structs name it (`frame` in 8 of the structs in `battle_private.h`) |
| 0x04 .. 0x1F | | per effect | each registered function uses these bytes its own way | upstream types them per function (`MagicAnimationData`, `BattleRampRepeatSlot`, ...); in the decompiled spell sources the members used are still `unkC` .. `unk1E` |

A slot is taken with `BattleEffectRegister(fn)` (called from 1,153 overlay functions) and addressed as
`g_BattleEffectSlots[g_BattleEffectCursor]` inside `fn`. Confidence: high for offsets 0 and 2; the rest is per
function and belongs with each function's decompilation, not in a shared type.

## 15. Rerun

```
python3 magic_data.py <checkout>/disks/us/MAGIC [--pc <unpacked magic.lgp>] [--out DIR]
python3 magic_data.py <MAGIC> --only sennkoku --dump      # every block of one overlay
```

Standard library only. Needs `overlays.tsv` (next to the script: file, sha1, code range per overlay). Writes
`COVERAGE.tsv` (bytes per class per overlay), `BLOCKS.tsv` (every block with its fields and how it was found),
`UNPLACED.tsv`, `SUMMARY.json` and, with `--pc`, `PC-ASSETS.tsv` (PC file -> PS1 blocks) and `OVERLAY-ASSETS.tsv`
(overlay block -> PC names). About 45 seconds for all 287.

Limits of the parser: the code range is taken from the table, not found; model blocks and sprite tables are
searched at every free word after the referenced addresses are tried, so the 25 + 13 blocks found by layout only
are the place to look for false positives; the vector arrays and the pointer tables are shape rules; opcodes of
the scripts are not walked.
