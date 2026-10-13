# BIONICLE: The Game (PC, 2003) – model data notes

Everything below was worked out from the game files and from `BIONICLE.exe`.
Offsets are little-endian.

## VOLT archives (`Data/*.vol`, `Data/*.avl`)
```
0x00 "VOLT"  u32 version(2)  u32 count  u32 nameTableSize
0x10 count x { u32 hash, u32 1, u32 nameOffset }      // nameOffset relative to end of this table
name entry: u32 offset, u32 0, u32 size, u32 0, char name[]  (NUL-terminated)
```
`.vol` holds `.PCM` (level), `.PCS` / `.PCSI` (entity "Strat Wad") files; `.avl` holds `.PCA` (audio).
`general.vol` holds loose DDS/BMP/TXT/CFM files.

## BIGB container (.PCM / .PCS / .PCSI)
```
0x00 "BIGB" u32 0x180 u32 0x74 u32 1
0x10 char title[64]        e.g. "Ta-Koro", "<Strat Wad>"
0x50 char "normal"
0x78 u32 A, u32 B          (streaming info, unused here)
0x80 u32 mainSize, u32 relocSize      (decompressed)
0x88 u32 mainPacked, u32 relocPacked  (compressed)
0x90 build command line string
0x190 compressed main stream, then compressed relocation stream
```
### Compression (BIONICLE.exe @ 0x441FC0)
Byte-oriented LZ/RLE. Read control byte `c`:
* `c < 0x40`  : copy `c+1` literal bytes.
* `0x40..0x7F`: RLE, repeat next byte `c-0x3E` times.
* `c >= 0x80` : back-reference; `w = int16(c<<8 | next)`, distance = `1 - (w >> 4)` (arithmetic shift),
  length = `(next & 0xF) + 2`.

### Relocation stream
u32 list. A value with bit 31 set starts a group (`type = v & 0x7FFFFFFF`), following values are
offsets in the main block that hold pointers (pointers are offsets into the main block).
Group types seen: 0x01 texture, 0x07 animated (layered, scrolling) texture, 0x20/0x21/0x22 draw batch,
0x23/0x24 vertex+index buffer, 0x113 RIFF sound, 0x04 animation data, others not decoded.

## Geometry
Vertex/index buffer (types 0x23, 0x24):
`u32 vtbl, u32 flags, u32 stride, u32 vertexCount, ptr vertices, u32 indexCount, ptr indices(u16)`
* stride 24: float xyz, u32 BGRA diffuse, float u, v      (batch FVF 0x142)
* stride 32: float xyz, float normal xyz, float u, v       (batch FVF 0x112)

Draw batch (types 0x20, 0x21, 0x22): `+0x04 FVF`, `+0x0C ptr vertex buffer`, `+0x10 ptr texture`,
`+0x38 ptr drawInfo`. Between them is a D3D render-state list.
drawInfo: `u32 primType(5 = triangle strip), u32 numVertices, u32 primCount, ptr node,
float center[3], u32 0, u32 minIndex, u32 startIndex`. Indices are absolute; strip length = primCount+2.
Node: name (char[16]) at `+0x20`, bounding sphere at `+0x10`.

Coordinates are D3D left-handed, Y up; the converter mirrors Z for glTF.
Entity meshes are stored in bind pose / model space; level meshes in world space.

## Textures
Texture object: `u32 vtbl, u32 w, u32 h, 0, ptr data, u32 flags, u32 mipCount, 0`.
`data` is a plain uncompressed TGA (8-bit colour-mapped with 24- or 32-bit palette, or 32-bit truecolour).
In 32-bit palettes the alpha channel often looks like a gloss/mask channel, not transparency.

## Skeletons (code: `rig/skel.py`)
A skeleton is a header followed by 0xB0-byte bone records. Each bone holds parent / first-child / next-sibling
indices (-1 = none), a name, and a 4x4 row-vector local matrix (D3D convention, translation in the last row).
World matrices are the product of locals from the root down. A few bones have a parent index outside the
table; the exporter hangs those under a synthetic `Armature` root.
Script-like byte patterns in the pack link a mesh node to its skeleton; when the link is missing the exporter
tries every skeleton in the pack, then every skeleton in the game, and keeps the one whose bind pose fits the
vertices best.

## Skin weights
Smooth-skinned meshes have a separate stream of 48-byte records (one per vertex) carrying bone indices and
weights. Rigid parts instead name a single bone per draw batch (`+0x3C` in the batch); every vertex of that
batch gets weight 1.0 on that bone.

## Animations (type 0x04)
A clip points into the name table of the skeleton it drives (the pointer lies in `[u32(h+8), u32(h+4))` of
the skeleton header). Clip header (all offsets from the clip start, pointers into the main block):
```
+0x04 ptr name        +0x10 u32 id           +0x18 u32 channelCount   +0x1C ptr channelIds (i32[])
+0x20 u32 keyCount    +0x24 ptr keyTimes (f32[], 0..1)                +0x28 ptr key data start
+0x2C ptr rotKeys (ptr[keyCount])             +0x30 ptr transKeys (ptr[keyCount])
+0x34 f32 speed (clip length in seconds = 1 / speed)                  +0x38, +0x3C f32 0.1 (blend times?)
```
* Channel id `c >= 0` drives bone `c` with rotation **and** translation; `c < 0` drives bone `-c-1` with
  rotation only. So the "-1" channel is bone 0 (`Scene Root`), which is never animated in practice.
* `rotKeys[k]`: one int16 quaternion per channel in D3DX order x, y, z, w; x, y, z are scaled by 1/32767 and
  w by 1/1024 before normalising. They are absolute local rotations that replace the bind rotation, not offsets from it.
* `transKeys[k]`: float x, y, z per channel. Key 0 lists **every** channel; later keys list only the
  `c >= 0` channels, in channel order. Values are offsets added to the bone's bind translation, in the
  parent's space; channels without later keys hold their key-0 offset for the whole clip. This carries
  pelvis bob, prop movement and full root motion (cutscene clips move characters tens of units).
* Blocks are stored back to back per key: rotations, then translations. All 1,627 clips in the retail
  data follow this layout exactly.
* There is no scale channel; the engine's pose blender (`BIONICLE.exe` @ 0x42C3F0) only mixes a
  quaternion and a translation per bone. The exporter interpolates keys linearly.

The exporter writes a translation track for every bone that any clip of that skeleton moves, in every
clip (unmoved bones get their bind translation), so switching clips in Blender never leaves a bone offset.

## Materials: transparency and blend modes
Each draw batch carries its D3D state as three lists:
```
+0x14 u32 material colour (ARGB; alpha = batch opacity)   +0x18 u32 (byte repeated 4x, unknown)
+0x1C u32 count, +0x20 ptr  (D3DRENDERSTATETYPE, value) pairs
+0x24 u32 count, +0x28 ptr  (stage, D3DTEXTURESTAGESTATETYPE, value) triples
+0x2C u32 count, +0x30 ptr  (stage, D3DSAMPLERSTATETYPE, value) triples (address U/V: wrap or clamp)
```
Render states seen: 14 ZWRITEENABLE, 15 ALPHATESTENABLE, 19 SRCBLEND, 20 DESTBLEND, 22 CULLMODE,
27 ALPHABLENDENABLE, 171 BLENDOP. Combinations:

| States | Meaning | glTF export |
|---|---|---|
| none, or 27=0 | opaque | `OPAQUE` |
| 27=1, or 19/20 without 27=0, with SRCALPHA / INVSRCALPHA (5/6) | alpha blend | `BLEND` |
| same with SRCALPHA / ONE (5/2), usually with z-write off | additive (glows, fire, sparks) | `BLEND` + `extras.btg.blend = "additive"` |
| 15=1 | alpha test | `MASK`, cutoff 0.5 |

Most level batches (types 0x20) have an empty list and are opaque. Entity batches (0x21, 0x22) list the
full state. Texture alpha only counts when blending or alpha test is on; on opaque batches it is a gloss
mask. Transparency can also come from vertex colour alpha (stride-24 vertices), which glTF multiplies in.
Every non-opaque material gets `extras.btg = {blend, depthWrite, srcBlend, dstBlend}` (D3DBLEND values).
A batch flagged alpha-blend with an opaque texture, no vertex alpha and full opacity is exported opaque.

## Animated textures (relocation type 0x07)
There are no flipbooks. An animated texture is a stack of texture layers whose UVs scroll and rotate:
```
+0x00 vtbl  +0x04 u32 w  +0x08 u32 h  +0x0C u32 layerCount (1-4)  +0x10 ptr layers (normally +0x20)
layer (0x40 bytes): ptr texture, f32 scrollU, f32 scrollV, f32 rotate, f32 tint[4] (always 1),
                    f32 unknown[3] (almost always 0, 1, 1), zero padding
```
Scroll values look like UV units per second and rotate like radians per second (e.g. -0.0349 for a slowly
turning sky, multiples of pi/18 elsewhere); this reading is inferred from the values, not from engine code.
The layers are combined like D3D texture stages: stage k's colour op (batch `+0x24` list, type 1) says how
layer k mixes with the layers before it (seen: ADD, SUBTRACT, BLENDTEXTUREALPHA, MODULATE); a final stage
modulates with the vertex colour. In the data: 2,325 one-layer, 302 two-layer, 96 three-layer and 20
four-layer records. glTF export: layer 0 is the base colour texture; every layer, with its image, op, scroll
rotate, and its texture address mode U/V from the batch sampler list (`+0x2C`, raw D3DTEXTUREADDRESS:
1 wrap, 2 mirror, 3 clamp), is listed in `material.extras.btg.layers`. A rotating layer is often followed by a
static MODULATE layer that masks the wrapped corners.

## Not decoded yet
Collision meshes (start of .PCM).
