# BIONICLE: The Game (PC, 2003) file format map

Read-only survey of `BIONICLE/Data/`. Nothing was modified. The full per-file index (archive, name, offset, size, first 16 bytes) is in [archive-index.json](archive-index.json); [list_vol.py](list_vol.py) regenerates it.

## Layer 1: archives (29 files, 425 entries)

| File | Count | Format | Notes |
|---|---|---|---|
| `NN.vol` | 14 | **VOLT v2** archive | One per level group (09–78). Holds PCM/PCS/PCSI. |
| `NN.avl` | 14 | **VOLT v2** archive | Same container; holds the PCA audio streams for that level group. |
| `general.vol` | 1 | **VOLT v2** archive | Shared config, sky/env textures. |

VOLT layout (verified): `"VOLT"`, u32 version=2, u32 entry count, u32 name-block size, then 12-byte hash entries (hash, 1, name offset), then per-file records `u32 offset, u32 0, u32 size, u32 0, char name[]`. Files are stored uncompressed, 2 KB aligned. 26 entries are 0-byte placeholders (mostly in `75.avl`).

## Layer 2: what's inside

| Ext | Count | Total | What it is |
|---|---|---|---|
| `.PCM` | 101 | 175 MB | **BIGB** wad, built from `.amf` (level/scene: geometry, textures, models). Header names it, e.g. "Ta-Koro", "Creatures - Rahi WAD", "Concept Art 3". |
| `.PCS` | 101 | 134 MB | **BIGB** "Strat Wad", built from `.ent` (entities/scripts, character models, sound effects). |
| `.PCSI` | 29 | 67 MB | **BIGB** "Strat Wad" variant (same `.ent` source, other build flags). |
| `.PCA` | 101 (75 non-empty) | 451 MB | **Headerless ADPCM audio** (music/ambience/speech per level). 36-byte blocks with valid IMA headers in nearly every file, i.e. Xbox-IMA ADPCM. Embedded WAV headers elsewhere declare format 0x69 (Xbox ADPCM), mono, 22050 Hz; that is the likely playback setting. A few files (e.g. 20-62, 20-26, 50-31/32, 78-02, 40-61) don't fit a clean mono 36-byte grid and are likely stereo (72-byte) or multi-stream. |
| `.DDS` | 21 | 2.4 MB | Standard DirectDraw Surface (sky/environment maps, frontend). Opens directly. |
| `.BMP` | 2 | 0.2 MB | Standard bitmaps (LensFlare, White). |
| `.TXT` / `.CFM` / `.CFL` / `.SNO` | 5 / 9 / 1 / 1 | tiny | Plain-text config: level list, effects, controller maps. |

BIGB layout (from samples): `"BIGB"`, header size 0x180, wad name string, build command line, then two data blocks with uncompressed/compressed sizes. Block data is compressed (back-references + literal runs + RLE), so models and textures are **not** visible until decompressed. PCS blocks contain embedded sound effects as a tagged RIFF/WAVE-like structure (66 found, e.g. `pickup01.wav`) and raw 16-bit textures.

**Video:** none present. `BIONICLE.exe` references `Movies\EA_Movie.bik` (Bink), but this copy has no `Movies` folder.

## Extraction tools

| Target | Tool | Status |
|---|---|---|
| VOLT `.vol`/`.avl` | Our `list_vol.py` already parses them; [VOLTArcUnpacker](https://github.com/Rackover/VOLTArcUnpacker/) (C#); JrMasterModelBuilder's VOLT Extractor (Python); Watto Game Extractor | Solved |
| BIGB decompression | JrMasterModelBuilder's BIGB Extractor (Python, `.pcm`); maver1k_XVII's `BioBIGB111.py` (`.pcs`) | Community scripts, from RRU threads below |
| Models (PCS/PCM) | maver1k_XVII's **Noesis** Python plugin (v0.1 beta), exports OBJ | Works for characters/props; level geometry "barely working", unreleased |
| Textures | maver1k_XVII's Noesis texture script v1.0 | Works; alpha holds a specular-like map |
| `.PCA` audio | **vgmstream** with a `.txth` file (codec XBOX, 22050 Hz, mono, interleave as needed) | Likely; needs testing. No dedicated tool known |
| Embedded SFX in PCS | Needs custom parse of the tagged RIFF chunks | Open problem per RRU |
| DDS/BMP/TXT | Any image viewer / text editor | Trivial |

Ready-made rips also exist on [The Models Resource](https://models.spriters-resource.com/pc_computer/bioniclethegame/).

Sources: [RRU: archive extracting](https://rockraidersunited.com/topic/4230-bionicle-the-game-game-archive-extracting-research-and-tools/), [RRU: models and textures](https://rockraidersunited.com/topic/5964-models-and-textures-research-and-tools/).
