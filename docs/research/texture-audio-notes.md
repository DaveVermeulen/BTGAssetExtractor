# BIONICLE (PC, 2003) extracted assets

Extracted from the read-only game folder `BIONICLE/Data`. No original files were modified.

* **2771 textures** as PNG in `textures/<level>/` (plus `textures/general/` for the skybox DDS and BMP files)
* **677 sounds** as 16-bit PCM WAV in `audio/<level>/sfx/` (432 mono effects and voice lines) and `audio/<level>/music_and_speech/` (245 stereo streams: music, cutscene audio)
* `other/general/`: the plain-text config files from general.vol, copied as-is
* `manifest.json`: every output file with its source archive and offset, size or length, and the other levels that hold an identical copy

Identical textures and sounds appear in many levels; each is written once, in the first level it was found, and `also_in` in the manifest lists the rest.

Texture file names are `<level>_<index>_<width>x<height>_<hash>.png`. The game keeps no texture names, so these are generated. Sound files keep the game's original names.

## Per level

| Level | Name (LEVELS.TXT) | Textures | Sounds |
|---|---|---|---|
| 9-95 |  | 31 | 7 |
| 9-96 |  | 33 | 1 |
| 9-98 |  | 4 | 0 |
| 9-99 |  | 2 | 0 |
| 10-00 | Tahu Only | 223 | 73 |
| 10-11 | Ta-Suva | 148 | 21 |
| 10-12 | Lock-In | 35 | 20 |
| 10-13 | Ta-Koro | 18 | 9 |
| 10-15 | Flow Platforms | 21 | 4 |
| 10-16 | Kofo Jaga | 4 | 1 |
| 10-21 |  | 74 | 10 |
| 10-61 | Battlefield | 38 | 16 |
| 15-00 | Ta Adrenaline | 109 | 17 |
| 15-41 | Ta Adrenaline | 38 | 13 |
| 15-42 | Ta Adrenaline | 1 | 3 |
| 15-43 | Ta Adrenaline | 0 | 1 |
| 15-44 | Ta Adrenaline | 0 | 1 |
| 20-00 | Toa Only | 40 | 44 |
| 20-22 | Link | 88 | 8 |
| 20-26 | between2021and2061 | 20 | 1 |
| 20-31 | Le Windmill (Centre) | 41 | 9 |
| 20-61 | le koro | 49 | 6 |
| 20-62 | Le MiniMap #3 | 17 | 7 |
| 21-00 | Branches | 153 | 17 |
| 21-41 | Branches | 17 | 5 |
| 21-42 | Branches | 4 | 1 |
| 21-43 | Branches | 3 | 1 |
| 22-00 | Level Complete Loader | 0 | 3 |
| 30-00 | <Gali Teleport Level> | 50 | 50 |
| 30-11 | Ga-Suva 3011 | 123 | 10 |
| 30-13 | 3015 Mini Map 01 | 50 | 8 |
| 30-21 | Ga-Kini | 38 | 1 |
| 30-55 |  | 16 | 0 |
| 30-61 | 3061 - Rahkshi Battle | 51 | 7 |
| 40-00 | <unnamed level> | 23 | 40 |
| 40-11 | Onu Suva | 65 | 13 |
| 40-22 | tween | 5 | 1 |
| 40-43 | Onu Tunnels | 36 | 2 |
| 40-61 |  | 39 | 10 |
| 40-66 |  | 24 | 3 |
| 40-77 | Take it to the bridge | 10 | 2 |
| 50-00 | Po Common | 137 | 25 |
| 50-31 | Po Start Section | 4 | 9 |
| 50-32 | Tween Room | 11 | 14 |
| 50-33 |  | 0 | 6 |
| 52-31 | Po Track Section 1 | 14 | 8 |
| 52-32 | Po Loop 1 Section 2 | 5 | 0 |
| 52-34 | Po Loop 1 Section 4 | 2 | 0 |
| 52-38 | Po Wahi Loop 1 Sect 8 | 1 | 1 |
| 53-31 | Po Wahi Loop 1 Sect 10 | 24 | 0 |
| 53-39 | Po Mine Cart Common | 3 | 12 |
| 60-00 | Ko Common Strats | 223 | 54 |
| 60-10 | Ko Suva | 7 | 10 |
| 60-11 | Ko timed section 1 | 0 | 3 |
| 60-13 | Ko timed section 3 | 1 | 6 |
| 60-15 | Ko timed section 5 - Kini | 17 | 6 |
| 60-16 | Ko Ice cave (vision mode) | 0 | 3 |
| 60-20 | Ko boulder run section 1 | 2 | 9 |
| 60-21 | Ko boulder run section 1 | 0 | 6 |
| 60-22 | Ko bohrok leader chase section 1 | 0 | 3 |
| 60-26 |  | 16 | 8 |
| 75-00 |  | 103 | 10 |
| 75-01 |  | 68 | 0 |
| 75-02 |  | 10 | 0 |
| 75-03 |  | 27 | 0 |
| 75-04 |  | 22 | 0 |
| 75-08 |  | 2 | 0 |
| 75-09 |  | 101 | 0 |
| 75-20 |  | 3 | 0 |
| 75-30 |  | 9 | 0 |
| 75-31 |  | 10 | 0 |
| 75-32 |  | 9 | 0 |
| 75-34 |  | 10 | 0 |
| 75-53 |  | 23 | 1 |
| 75-54 |  | 1 | 0 |
| 78-00 |  | 21 | 16 |
| 78-01 |  | 90 | 15 |
| 78-02 |  | 31 | 6 |
| general |  | 23 | 0 |

## Formats (for re-running or extending)

* **VOLT archives** (`.vol`, `.avl`): see `tools/vol.py`.
* **BIGB wads** (`.PCS`, `.PCSI`, `.PCM`): 0x180 header, then two compressed sections. Header 0x78 = sfx bank size, 0x7C = streamed audio size, 0x80/0x84 = unpacked sizes, 0x88/0x8C = packed sizes.
* **Compression**: byte-oriented LZ. Control byte `c < 0x40`: copy `c+1` literal bytes. `0x40 to 0x7F`: repeat the next byte `(c & 0x3F) + 2` times. `0x80 and up`: read a big-endian signed 16-bit word `w`, copy `(w & 15) + 2` bytes from `-(w >> 4) + 1` bytes back. See `argz()` in `tools/fast.c`.
* **Textures**: inside the unpacked wad, each texture record is `[0x00545C6C][u32 w][u32 h][0][u32 ptr][u32 size]`, and `ptr + 8` holds a complete TGA image (8-bit palette with 24 or 32-bit colours, or 32-bit truecolour).
* **Audio**: the wad holds `RIFF/WAVE` (sfx) and `RIFF/WAVS` (stream) headers with `fmt`, `fact`, `name` and `strm` (offset, size) chunks. The data sits in the matching `.PCA` in the `.avl`: the sfx bank starts at 0 and the streams start at the bank size rounded up to 0x800. The codec is Xbox IMA ADPCM (format 0x69).

Re-run (Python 3 with numpy and Pillow, plus gcc):

```
gcc -O2 -shared -fPIC -o tools/fast.so tools/fast.c
python3 tools/extract.py <path to BIONICLE/Data> <output folder>
```

Not extracted: 3D models, level geometry, animations and scripts (still inside the unpacked wads).
