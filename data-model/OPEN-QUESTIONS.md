# Open questions for the maintainer

Choices that are yours. Each comes with what the data model found, so a short answer is enough.
The model itself is in `MAGIC-DATA-MODEL.md`; the type sketch is `magic_data.h`.

1. **Extraction at build time.** 97.9 % of the non-zero data of the 287 overlays is in formats that can be walked
   (TIM, model block, skeleton container, animation record, sprite table). Should these be split out of the
   overlay into files at build time the way TIM images are handled today, or stay as `INCBIN`-style data inside
   each overlay's C file? If split: one file per block, or one per overlay?
2. **File names for extracted blocks.** The PC release names most of them (`ayasii.s`, `tupondat.p00`,
   `wind_1.p`): 764 sprite tables, 249 animation records and 1,349 model files line up with a PS1 block
   (`OVERLAY-ASSETS.tsv`). Use those names, or names derived from the overlay and offset? The PC names are not
   unique (the same `smoke_1.s` exists in several folders) and 124 overlays have no PC name at all.
3. **Where the types live.** The model block records (`ModelTexTri`, `ModelTexQuad`, `ModelColTri`,
   `ModelColQuad`) are read by `BattleDrawModel` in the battle executable: `battle.h` next to
   `ModelRenderDesc`, or a new header shared by battle and magic?
4. **Bone entry field name.** `BattleModelBoneEntry.z` (u16) is the bone length stored negative; the PC `.d` file
   holds the same number as a float length. Keep `z`, or rename and make it `s16`?
5. **Model block as C.** A model block has four variable-length lists one after another, so it has no single C
   struct. Is a set of record types plus a comment on the order acceptable, or do you want a macro or generator
   that emits each block as initialised data?
6. **Animation records.** They are a bit stream behind a 5-byte header. Keep them as bytes (`u8[]` from a file),
   or do you want them decoded to a readable form and re-encoded by the build? The decoder exists
   (`magic_data.py`, `decode_anim`); an encoder that reproduces the bytes does not.
7. **The zero-filled buffers.** 175 overlays store 0x18000 or more zero bytes (two 0xC000 primitive buffers).
   In C these are plain zero-initialised arrays; is `u8 buf[2][0xC000]` per overlay fine, or should they be one
   shared declaration (macro) since the size is the same everywhere?
8. **Per-overlay variables and tables.** 55 KB are the overlays' own tables (delay tables, state words). The model
   leaves these to each overlay's C. Agreed, or do you expect them in the asset pipeline too?
9. **Naming of the two container kinds.** Upstream has `EffectModelHeader` / `EffectModel` for the skeleton
   container. The 16-entry animation table in the 43 limit-break overlays has no upstream name; "animation pack"
   is ours. What should it be called, and do you know its reader?
10. **Scope of a first step.** Would a parser like `magic_data.py` in `tools/` (reporting coverage, no
    extraction) be useful to you on its own, before any overlay import?
