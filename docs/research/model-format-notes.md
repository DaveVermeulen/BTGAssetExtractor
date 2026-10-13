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
Group types seen: 0x01 texture, 0x07 animated texture, 0x20/0x21/0x22 draw batch,
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
the skeleton header). Per bone it stores key times normalised to 0..1 and int16 quaternions in D3DX order;
x, y, z are scaled by 1/32767 and w by 1/1024 before normalising. Clip length in seconds = 1 / speed field.
Only rotations are exported.

## Not decoded yet
Animation translations / root motion, a channel id of -1 seen in some clips, collision meshes (start of .PCM),
material blend modes and transparency, animated texture frames past the first.
