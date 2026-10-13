# BTG Asset Extractor

Extract textures, sounds, 3D models and rigged, animated characters from your own copy of
**BIONICLE: The Game** (2003, PC).

The tools read the game's `.vol` / `.avl` archives (they never modify them) and write standard
files you can open anywhere: PNG textures, WAV audio and glTF 2.0 models that import straight into
Blender.

> **No game files or extracted assets are included in this repository, and none will be.**
> You need your own legally obtained copy of the game. See [Legal](#legal).

## What you get

| Tool | Output |
|---|---|
| `tools/bionicle_extract.py` | ~2,770 textures (PNG), ~680 sounds and music tracks (16-bit WAV), the plain-text config files, and a `manifest.json` |
| `tools/btg_models.py` | Every level as one glTF in world space (63 levels), plus ~2,650 unique entity meshes (characters, Rahi, masks, props, skydomes) in bind pose |
| `tools/btg_rigged.py` | ~290 rigged characters (Toa, Toa Nuva, Matoran, Rahkshi, Bohrok, Rahi…) with skeleton, skin weights and animation clips |

Counts are from the retail PC release; your numbers may differ slightly by version.

## Requirements

* **BIONICLE: The Game** for PC, installed. You need its `Data` folder, e.g.
  `C:\Program Files (x86)\LEGO Interactive\BIONICLE\Data`. It holds files like `10.vol`, `10.avl` and `general.vol`.
* **Python 3.8 or newer** ([python.org](https://www.python.org/downloads/)).
* For the 3D model tools only: **numpy** and **Pillow**.
* Disk space: roughly 1.2 GB for textures and audio, and about 550 MB for the models and characters.

Windows, macOS and Linux all work; the tools are plain Python.

## Install

```sh
git clone https://github.com/DaveVermeulen/BTGAssetExtractor.git
cd BTGAssetExtractor
python -m pip install -r requirements.txt
```

On Windows, use `py` in place of `python` if `python` isn't on your PATH.
Skip the `pip install` line if you only want textures and audio.

## Usage

In the examples below, replace the `Data` path with the one on your machine. Quote it if it contains spaces.
Each tool prints its usage when run without arguments.

### 1. Textures and audio

```sh
python tools/bionicle_extract.py "C:\Program Files (x86)\LEGO Interactive\BIONICLE\Data" output
```

To extract only some level groups, add a comma-separated list of archive numbers
(`10` means `10.vol` and `10.avl`):

```sh
python tools/bionicle_extract.py "<path to Data>" output 10,20
```

This writes:

```
output/
  textures/<level>/*.png                 textures, plus textures/general/ for sky DDS and BMP files
  audio/<level>/sfx/*.wav                mono sound effects and voice lines
  audio/<level>/music_and_speech/*.wav   stereo music, ambience and cutscene audio
  other/general/*                        text config files from general.vol (level list etc.)
  manifest.json                          every output file, its source archive and offset, and duplicates
  texture_index.json                     maps texture records in the game files to PNG names
```

Identical textures and sounds appear in many levels. Each is written once, in the first level it
was found in, and `also_in` in `manifest.json` lists the others. The game stores no texture names,
so texture files are named `<level>_<index>_<width>x<height>_<hash>.png`. Sounds keep the game's
original names.

### 2. Levels and static models

```sh
python tools/btg_models.py "<path to Data>" output/models
```

This writes:

```
output/models/
  levels/<level>.gltf                  whole level geometry, e.g. 10-13.gltf is Ta-Koro
  entities/<name>__<hash>.gltf         each entity mesh in bind pose, deduplicated
  index.csv                            which file inside the game archives produced what
```

Each `.gltf` comes with a `.bin` and its PNG textures; keep them together.

### 3. Rigged and animated characters

```sh
python tools/btg_rigged.py "<path to Data>" output/models
```

This writes:

```
output/models/
  characters/<name>__<hash>.gltf       mesh + skeleton + skin weights + animation clips
  characters.csv                       source file and bone, clip and mesh counts per character
```

## Opening the models in Blender

1. **File → Import → glTF 2.0 (.glb/.gltf)** and pick a `.gltf` file.
2. For a rigged character, select the armature and open the **Action Editor** (Dope Sheet → Action
   Editor) or the **NLA Editor** to choose an animation clip.
3. Level geometry is in world space and can be large; press numpad `.` to frame it.

The output passes the [Khronos glTF validator](https://github.khronos.org/glTF-Validator/) with no
errors, so other glTF viewers work too.

## Known gaps

* Animations carry **bone rotations only**; translations and root motion are not decoded yet.
* Material **transparency and blend modes** are not applied, so some foliage, glass and effects look opaque.
  In 32-bit palettes the alpha channel is often a gloss mask, not transparency.
* **Animated textures** export their first frame only.
* **Collision meshes** and level scripts are not extracted.
* No video: the retail data has no Bink movies even though the game looks for `Movies\EA_Movie.bik`.

Format details, including what is still unknown, are in [docs/FORMAT_NOTES.md](docs/FORMAT_NOTES.md).
Pull requests that close any of these gaps are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md).

## Repository layout

| Path | What |
|---|---|
| `tools/` | the three extractors above, plus `volt.ps1`, a PowerShell-only VOLT archive lister/unpacker |
| `docs/FORMAT_NOTES.md` | consolidated file format notes |
| `docs/formats.md` | first-pass survey of the install and archive layout |
| `docs/research/` | working notes from the reverse-engineering (texture/audio and model notes, archive index) |
| `output/` | where extracted assets go; git-ignored |

## Credits

These tools build on years of research by the
[Rock Raiders United](https://rockraidersunited.com/) community, in particular the
[archive extracting](https://rockraidersunited.com/topic/4230-bionicle-the-game-game-archive-extracting-research-and-tools/)
and [models and textures](https://rockraidersunited.com/topic/5964-models-and-textures-research-and-tools/)
threads, with work by JrMasterModelBuilder, maver1k_XVII and others. Thanks also to
[VOLTArcUnpacker](https://github.com/Rackover/VOLTArcUnpacker/) by Rackover.

## Legal

The code and documentation in this repository are released under the [MIT License](LICENSE).

This project does **not** include, distribute or link to any game files or assets extracted from
them. It is meant for personal use, preservation, research and fan projects with a copy of the game
you own. Assets you extract remain the property of their owners; check that your use of them is
allowed before sharing them.

LEGO, the LEGO logo and BIONICLE are trademarks of the LEGO Group. BIONICLE: The Game was developed
by Argonaut Games and published by Electronic Arts. This project is not affiliated with, endorsed
or sponsored by the LEGO Group, Argonaut Games or Electronic Arts.
