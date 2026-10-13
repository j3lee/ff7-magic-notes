# FF7 (PS1) spell overlays: what they share

Notes and measurements on the 287 `MAGIC/*.BIN` overlays of Final Fantasy VII (US, PlayStation), made while
working on [ff7-decomp](https://github.com/Xeeynamo/ff7-decomp). Everything here was measured from the original
files, not from decompiled C. No game data is in this repository: file names, sizes, hashes and counts only.

- **[Treemap](https://j3lee.github.io/ff7-magic-notes/)**: every overlay drawn by size. Four views: each file by
  content, all files rolled up by content, code by spell, and code grouped into families of identical functions.
- **[MAGIC-OVERLAYS-SHARED.md](MAGIC-OVERLAYS-SHARED.md)**: the write-up. Scale, shared code, the common skeleton
  of an overlay, data and assets, the same data in the PC release, and what was not measured.
- `MAGIC-OVERLAYS-FAMILIES.tsv`: one row per family of instruction-identical functions (311 families).
- `MAGIC-OVERLAYS-OVERLAYS.tsv`: one row per overlay (file, load address, sha1, code and data sizes).
- `MAGIC-OVERLAYS-NUMBERS.json`: every figure quoted in the write-up.
- `magic_shared.py`: the script that produces the tables from the overlay files (standard library only).

## The short version

- All 287 overlays load at `0x801B0000` and are entered through one table in the battle executable.
- Of the whole 45.5 MB, code is 3.9%, TIM images are 43% and an empty buffer area the effect draws into is 39%.
- 1,868 of the 3,959 functions are instruction-identical copies of a function in another overlay (311 families),
  but they are the small ones: 29% of code bytes. A further 262 functions are at least 85% alike to one elsewhere.
- "Identical" here means the same instructions in the same order, with addresses and constants allowed to differ.

## Two ways of counting the data

The write-up and the treemap split the non-code bytes slightly differently, so their percentages differ:

- The write-up (section 5) gives shares of the **data bytes** (43.7 MB), and counts every run of zeros outside an
  image as zero fill: images 45.0%, zero fill 47.9%, everything else 7.1%.
- The treemap gives shares of the **whole file** (45.5 MB), and a model or animation block keeps the zero bytes
  inside it: images 43%, empty draw buffers 39%, models 7.6%, other zero fill 4.5%, code 3.9%.

The image bytes are the same in both (19.68 MB).
