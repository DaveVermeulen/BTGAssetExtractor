# BIONICLE: The Game (PC, 2003) file formats

Game: Argonaut Games / EA, built from the PS2 pipeline ("L:\PS2\CurrentData\PC\...").
Install: `C:\Program Files (x86)\LEGO Interactive\BIONICLE` (871 MB, 62 files).
All little-endian. Status: **solved**, **partial**, **unknown**.

## Install layout

| Path | What |
|---|---|
| `BIONICLE.exe` | game executable (contains the decompressor, useful for reversing) |
| `binkw32.dll` | Bink video codec (no .bik files found in Data, so FMVs may be absent or packed) |
| `Data/general.vol` | shared data: skyboxes/env maps (DDS), controller configs, level list |
| `Data/NN.vol` | per-area level data (`.PCS`, `.PCM`, `.PCSI`) |
| `Data/NN.avl` | per-area audio (`.PCA`) |
| `Support/` | EA help files and readmes |

Areas (from `LEVELS.TXT`): 10 Ta-Koro, 15 Ta adrenaline, 20/21 Le-Koro/Branches,
22 level-complete loader, 30 Ga-Koro, 40 Onu-Koro, 50/52/53 Po-Koro, 60 Ko-Koro,
75/78 Makuta / finale. Level ids are `AA-SS` (area-section).

## VOLT archive (.vol / .avl), solved

Reader: `tools/volt.ps1`. Uncompressed, data aligned to 0x800, padding byte `i` (0x69).

```
0x00 "VOLT"
0x04 u32 version = 2
0x08 u32 count
0x0C u32 recordBlockSize
0x10 count x { u32 nameHash, u32 1, u32 offsetIntoRecordBlock }   (sorted by hash)
     record block: { u32 dataOffset, u32 0, u32 dataSize, u32 0, char name[] NUL }
```

371 entries in total, all extract cleanly (829 MB):

| Ext | Count | MB | What |
|---|---|---|---|
| .PCA | 101 | 451 | level audio bank, no header, starts with compressed-looking audio (unknown codec) |
| .PCM | 101 | 175 | level "model/world" wad (BIGB). Some are 2 KB stubs with an empty payload |
| .PCS | 101 | 134 | "Strat Wad": scripts/entities + level assets (BIGB) |
| .PCSI | 29 | 67 | variant of .PCS for some levels (same BIGB layout, slightly different contents) |
| .DDS | 21 | 2.4 | standard DirectDraw Surface env maps/skies, open directly |
| .BMP | 2 | 0.2 | standard bitmaps |
| .TXT / .CFM / .CFL / .SNO | 16 | <0.1 | plain-text config (levels, controllers, effects) |

## BIGB wad (.PCM / .PCS / .PCSI), partial

```
0x000 "BIGB"
0x004 u32 0x180 (header size)
0x008 u32 0x74
0x00C u32 1
0x010 char[64] level title ("Ta-Koro", "<Strat Wad>", ...)
0x050 char[32] mode ("normal")
0x078 u32 ?   (PCS/PCSI only; same value in matching PCS and PCSI)
0x07C u32 ?   (PCS/PCSI only)
0x080 u32 uncompressed size, section A (main data)
0x084 u32 uncompressed size, section B (likely pointer/relocation table)
0x088 u32 compressed size, section A
0x08C u32 compressed size, section B
0x090 char[] build command line ("-disablereport -platform 2 C:\Buildatron\AMFandENT\10-13.amf ...")
0x190 compressed data: section A then section B
```

The payload is compressed with an unidentified LZ-style scheme (control bytes interleaved
with literals). 681 MB uncompressed in total. **Next step:** find the decompressor in
`BIONICLE.exe` and port it, then map the decompressed sections (meshes, textures, animations).

Source asset names in the build lines: `.amf` (models/world) feeds `.pcm`, `.ent` (entities) feeds `.pcs`.

## Not found
- No standalone texture or model files; they live inside the compressed BIGB wads.
- No public documentation or tools for these formats were found (searched October 2026).
