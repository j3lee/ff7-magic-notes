// magic_data.h : SKETCH FOR DISCUSSION, NOT A PATCH.
//
// The C types that the data model in MAGIC-DATA-MODEL.md implies for the non-code data of the MAGIC overlays.
// Types upstream already has are reused and only referred to here (marked "upstream"); the rest are new, named
// plainly, with `unk` where no reader and no PC counterpart names the field. Section numbers refer to the
// document. Nothing here was compiled against the tree.
#ifndef MAGIC_DATA_H
#define MAGIC_DATA_H

#include <game.h>

// ---- upstream, unchanged ------------------------------------------------------------------------------------
// battle.h:           ModelRenderDesc (0x10), ModelRenderFlags, SpriteQuad (0x14), SpriteFrame, SpriteAnim,
//                     SpriteRenderDesc (0xC), SpriteQuadFlags
// battle_private.h:   BattleModelBoneEntry (8), BattleEffectSlot (0x20, union), MagicAnimationData
// src/magic/magic.h:  EffectModelHeader, EffectModel, EFFECT_MODEL_SKELETON, MagicEntry

// ---- section 5: model block (what ModelRenderDesc.model points at; read by BattleDrawModel) -------------------
// Layout in memory, in this order; the lists have no fixed offsets because each count sizes the next part:
//   ModelBlockHead, SVECTOR vertices[vertexBytes / 8],
//   ModelTexListHead,  ModelTexTri  [count],
//   u32 texQuadCount,  ModelTexQuad [texQuadCount],
//   ModelColListHead,  ModelColTri  [count],
//   u32 colQuadCount,  ModelColQuad [colQuadCount]
// Every `vertex` value is a byte offset into the vertex array (index * 8).

typedef struct {
    /* 0x0 */ u32 vertexBytes; // size of the vertex array; the face lists start at 4 + vertexBytes
    /* 0x4 */ SVECTOR vertices[1];
} ModelBlockHead;

typedef struct {
    /* 0x0 */ u16 count;
    /* 0x2 */ u16 tpage; // & 0x19F, added to ModelRenderDesc.tpage unless MODEL_PRIM_TPAGE
} ModelTexListHead; // size:0x4

typedef struct {
    /* 0x0 */ u16 count;
    /* 0x2 */ u16 unk2; // not read; 0 in all 1,588 blocks
} ModelColListHead; // size:0x4

typedef struct {
    /* 0x0 */ u16 vertex[3];
    /* 0x6 */ u8 shade; // grey level of the packet colour under MODEL_DEPTH_CUE
    /* 0x7 */ u8 page;  // per-face tpage under MODEL_PRIM_TPAGE; packet bits under MODEL_PRIM_PACKET_BITS
    /* 0x8 */ u8 u0;
    /* 0x9 */ u8 v0;
    /* 0xA */ u16 clut; // ModelRenderDesc.clut is added
    /* 0xC */ u8 u1;
    /* 0xD */ u8 v1;
    /* 0xE */ u8 u2;
    /* 0xF */ u8 v2;
} ModelTexTri; // size:0x10, drawn as POLY_FT3

typedef struct {
    /* 0x00 */ u16 vertex[4];
    /* 0x08 */ u8 u0;
    /* 0x09 */ u8 v0;
    /* 0x0A */ u16 clut;
    /* 0x0C */ u8 u1;
    /* 0x0D */ u8 v1;
    /* 0x0E */ u8 u2;
    /* 0x0F */ u8 v2;
    /* 0x10 */ u8 u3;
    /* 0x11 */ u8 v3;
    /* 0x12 */ u8 shade;
    /* 0x13 */ u8 page;
} ModelTexQuad; // size:0x14, drawn as POLY_FT4

typedef struct {
    /* 0x0 */ u16 vertex[3];
    /* 0x6 */ u16 unk6;      // not read
    /* 0x8 */ CVECTOR color[3]; // color[0].cd is the GPU command (0x30)
} ModelColTri; // size:0x14, drawn as POLY_G3

typedef struct {
    /* 0x0 */ u16 vertex[4];
    /* 0x8 */ CVECTOR color[4]; // color[0].cd is the GPU command (0x38)
} ModelColQuad; // size:0x18, drawn as POLY_G4

// ---- section 6: skeleton section (EffectModelHeader.offsets[EFFECT_MODEL_SKELETON]) --------------------------
// EffectModelHeader.offsets: [0] skeleton section, [1] script block, [2 .. numOffsets - 2] animation records,
// [numOffsets - 1] a TIM (empty in the summons).
#define EFFECT_MODEL_SCRIPTS 1    // index into EffectModelHeader.offsets
#define EFFECT_MODEL_FIRST_ANIM 2 // index into EffectModelHeader.offsets

typedef struct {
    /* 0x0 */ u16 boneCountMinus1; // BattleGetModelBoneNumAndInitBones: count = this + 1
    /* 0x2 */ u16 unk2;            // 0 in all 23 containers
    /* 0x4 */ BattleModelBoneEntry bones[1]; // bones[0] is the root; model blocks follow the table
} EffectModelSkeleton;

// ---- section 7: script block (EffectModelHeader.offsets[1]) ---------------------------------------------------
#define EFFECT_MODEL_NUM_SCRIPTS 8

typedef struct {
    /* 0x00 */ s32 scriptOffsets[EFFECT_MODEL_NUM_SCRIPTS]; // from the start of the block; the loader makes
                                                            // them addresses. All 0x38 in the 23 blocks
    /* 0x20 */ u8 unk20[0x18]; // two value sets only (7 spell containers, 16 summon containers)
    /* 0x38 */ u8 script[1];   // byte code; a byte below 0x8E is an animation index
} EffectModelScripts;

// ---- section 8: animation record -------------------------------------------------------------------------------
// The header is 5 bytes, so it cannot be a padded C struct; the stream starts at byte 5.
typedef struct {
    /* 0x0 */ u16 frames;
    /* 0x2 */ u16 size;    // bytes of bit stream after this header
    /* 0x4 */ u8 key;      // an angle is stored in 12 - key bits; 0 in all 253 records
    /* 0x5 */ u8 stream[1]; // bit stream, most significant bit first (document, section 8)
} BattleAnimRecord;

// ---- section 9: animation pack (limit-break overlays) ----------------------------------------------------------
// No reader was read for this one: the name and the split into 8 + 8 records are a reading of the bytes.
#define ANIM_PACK_PLACEHOLDER 0x1A30 // a 4-byte entry with no animation

typedef struct {
    /* 0x0 */ u32 count;      // 16 in 41 packs, 17 in 2
    /* 0x4 */ u32 offsets[1]; // from the start of the pack, each to a BattleAnimRecord or a placeholder
} AnimPack;

// ---- section 4: the primitive double buffer --------------------------------------------------------------------
// Zero bytes stored in the file. The overlays that are decompiled declare the halves separately
// (g_SennkokuPrimBuffer0 / 1); as one object it would be:
#define MAGIC_PRIM_BUFFER_SIZE 0xC000
// u8 g_<Overlay>PrimBuffer[2][MAGIC_PRIM_BUFFER_SIZE]; // indexed by g_dbIndex

// ---- section 14: effect slot -----------------------------------------------------------------------------------
// Upstream's BattleEffectSlot is a union of per-function views. The part every view shares:
typedef struct {
    /* 0x00 */ s16 state; // -1 frees the slot
    /* 0x02 */ s16 frame;
    /* 0x04 */ u8 perEffect[0x1C]; // used by each registered function in its own way
} MagicEffectSlotCommon; // size:0x20

#endif
