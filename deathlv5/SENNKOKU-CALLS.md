# sennkoku: what the code does when the effect runs (static reading)

Source: `src/magic/sennkoku.c` of ff7-decomp (275 lines, 7 functions) and `SENNKOKU.BIN` (120,304 bytes, 2,352 of code).
Everything below is read from the code; frame numbers are values of the effect slot's own counter
(`AnimationFrame`), which advances once per call and only while the battle's pause word `D_80062D98` is 0. Rows of
`SENNKOKU-MAP.tsv` carry the same facts per statement group.

## 1. Set-up (runs once, at cast time)

| step | function | calls, in order |
|---|---|---|
| 1 | `MAGIC_DeathSentence` (mode 0) or `MAGIC_Roulette` (mode 1) | store mode; call `SennkokuMainSetup(targetMask)`; return `&g_SennkokuEffectModel` |
| 2 | `SennkokuMainSetup` | `BattleSetLoadTimToVram(TIM at +0x930)`; store target mask; find the first set bit of the mask among 10 actors; `BattleEffectRegister(SennkokuStartTask)` |
| 3 | `SennkokuStartTask` (first call of the new slot) | free its own slot; then mode 0: `BattleEffectRegister(SennkokuHitTimeline)` + `BattleGetPartPosition(target, bone 10)`; mode 1: `BattleEffectRegister(SennkokuRouletteSpinTick)` + `BattleGetPartPosition(target, bone 10)`, build the candidate list (units alive: mask minus downed), `rand() % count` for the starting cursor, step 0, phase 0, delay = table[0] |

## 2. Death Sentence (mode 0): `SennkokuHitTimeline`, one call per frame

| frame f (slot counter) | what happens | API |
|---|---|---|
| 1 | event 1 pushed (effect model start), slot Pos and RotY copied into it | `BattleEventQueuePush` |
| 0x11 (17) | sound 0x1A4, panned from the slot position | `BattlePositionToStereoPan`, `BattleAkaoCommand(0x20, ...)` |
| 0x20 (32) | event 2 pushed (effect model end) | `BattleEventQueuePush` |
| 0x24 (36) | hit applied to the target unit (only when not paused) | `BattleEffectHitTarget` |
| >= 50 (0x32) | slot freed (`StartFrame = -1`) | none |

f advances by 1 at the end of each call that is not paused. The three event/sound frames are tested before the pause
word is read, so while the battle is paused they would repeat on every call; the hit frame is not.

## 3. Roulette (mode 1): `SennkokuRouletteSpinTick`, one call per frame

State is `g_SennkokuPhase` (0 = spinning, 1..44 = locked), plus cursor, step and step delay.

| state | what happens each call | advances when |
|---|---|---|
| phase 0, spinning | delay--; at <= 0: cursor to the next candidate (wraps), step++, sound 0x1E3 panned from the unit under the cursor, delay = `table[step]` (table of 48: 40 x 1, then 2 2 3 3 4 4 6 6) | step reaches 48 and the cursor is on the target unit: phase = 1, delay = table[47] = 6. If the cursor is not on the target at step 48 it keeps stepping every 6 frames until it is |
| every call, any phase | publish masks to `D_800D3544` / `D_800D3546`; project the unit under the cursor; draw the pointer quad (24 pixels left of a party unit, mirrored for enemies) into the primitive cursor `D_80163C74` | - |
| phase 1..9 | pointer stays; phase++ per call | phase 10 |
| phase 10 | `BattleEffectRegister(SennkokuHitTimeline)` and Pos/RotY copied: from here section 2 runs in its own slot | next call |
| phase 11..44 | phase++ | phase >= 45: this slot freed |

Counting frames from the start of the spin (unpaused): the 48 table entries sum to 70, so the cursor has made 48 steps
after 70 calls if it happens to be on the target, otherwise 6 more per extra step; lock-in phase 1 is then followed by
the hit timeline starting 9 calls later (phase 10) and the spin slot ending at phase 45; the hit timeline then runs its
50 frames, so the target is hit 36 frames after the timeline starts.

## 4. Calls by routine

| routine | address | called from |
|---|---|---|
| `BattleEffectRegister` | 0x800BBEAC | MainSetup, StartTask (x2), SpinTick |
| `BattleSetLoadTimToVram` | 0x800D2980 | MainSetup |
| `BattleGetPartPosition` | 0x800D3994 | StartTask (x2), SpinTick (x2) |
| `BattleEventQueuePush` | 0x800D4FA8 | HitTimeline (x2) |
| `BattleAkaoCommand` + `BattlePositionToStereoPan` | 0x800D55F4 / 0x800D56A8 | HitTimeline, SpinTick |
| `BattleEffectHitTarget` | 0x800D5774 | HitTimeline |
| `SetRotMatrix`, `SetTransMatrix`, `RotTransPers` | 0x8003B48C / 0x8003B51C / 0x8003BBDC | SpinTick |
| `rand` | 0x80042DA8 | StartTask |

`SennkokuBufferFlip` (0x801B0000) has no caller and no pointer to it exists in the file.
