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
| `tools/btg_models.py` | Every level as one glTF in world space (63 levels), plus ~760 entity meshes (characters, Rahi, masks, props, skydomes) in bind pose, each written once for the whole game, the collision meshes, and where every entity is placed in each level |
| `tools/btg_rigged.py` | ~170 rigged characters (Toa, Toa Nuva, Matoran, Rahkshi, Bohrok, Rahi…), one file per body variant, with skeleton, skin weights and animation clips (rotation, translation and root motion) |

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
  other/text/game_text.csv               every line of game text in six languages (also game_text.json)
  manifest.json                          every output file, its source archive and offset, and duplicates
  texture_index.json                     maps texture records in the game files to PNG names
```

`game_text.csv` has one row per line of text: menus, help and hint messages, objectives, Rahi
descriptions and the credits, in English, French, German, Spanish, Italian and Danish, with the levels that
use it (756 lines). Open it in a spreadsheet as UTF-8. Line breaks are kept, and the controller-button
icons the game draws inline are written as `[button N]`. The game builds a few messages from two pieces,
such as a free-space warning and the number of blocks it needs, so those appear as two rows.

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
  collision/<level>.gltf               the level's collision mesh, one material per surface type
  entities/<name>__<hash>.gltf         each entity mesh in bind pose, written once for the whole game
  entities.csv                         every entity file with the levels and source files that use it, and its near-duplicate group
  placements/<level>.gltf              where every creature, pickup, prop, trigger and effect is placed (also as .json)
  placements.csv                       every placement in every level
  index.csv                            which file inside the game archives produced what
```

Each `.gltf` comes with a `.bin` and its PNG textures; keep them together.

The collision meshes (63 levels) line up with the level geometry. They include the invisible walls that
keep the player on the path, so some are much taller than the visible level. Each surface type the game
uses gets its own material, named `surface_<number>` and coloured so the types are easy to tell apart.
The numbers are the game's own surface codes. In Ta-Koro, for example, 5 is the lava and 3 the water.
`index.csv` lists the triangle count per surface type.

The placements (about 3,850 in 86 levels, menus and cutscene sets) come from each level's strat (entity script) table. Every placement is an empty node named
`<index> <strat>`, such as `002 IrisDoor` or `024 Nui_Kopen_Mk2`, at the right position and rotation, so
importing `placements/10-13.gltf` together with `levels/10-13.gltf` shows where everything sits in Ta-Koro.
Strats that follow a route (moving platforms, canisters, camera shots, the skydome) get their waypoints as a
line, and triggers get their box. A strat is the game's own name for a script, so the list also has
invisible things like `SoundPlayer`, `Fog`, `LoadNextArea` and camera triggers. The node's extras and
`placements.csv` list the meshes the strat's script refers to (`script_models`). That list is per script
file, so strats that share a file share the list.

### 3. Rigged and animated characters

```sh
python tools/btg_rigged.py "<path to Data>" output/models
```

This writes:

```
output/models/
  characters/<name>__<hash>.gltf       mesh + skeleton + skin weights + animation clips
  characters.csv                       source file, near-duplicate group and bone, clip and mesh counts per character
  cameras/camera_<level>__<hash>.gltf  animated cutscene cameras, one animation per cutscene clip
  cameras.csv                          source file, clip count and clip lengths per camera
```

Cutscene characters and their cameras share one origin, so load a camera file into the same Blender scene
as the characters and play the clip of the same length on each to watch the cutscene from the game's
point of view. The game doesn't store the camera's field of view with the rig; the files use 46 degrees
vertical (4:3), which frames the Ta-Koro cutscene as expected but may differ from the game's.

A mesh that appears in several levels is exported once. Two copies count as the same when they draw the
same triangles with the same vertex data and texture pixels (plus blend states for entities and bone
weights for characters); the node name doesn't matter. Each file lists every level and source that uses
it in `asset.extras.btg` (`names`, `levels`, `sources`), and `entities.csv` / `characters.csv` hold the
same mapping.

Files that are versions of one model are grouped, such as the same Rahi in two levels with a slightly
different mesh. Files share a `body` when at least 80% of each one's vertices lie within 1% of the model
size of the other's; for characters, their skeletons must also share most bone names. One body can carry
several characters (all Matoran, the Bohrok kinds, the Turaga), so each body is split by the mean colour
of its textures into `group`s, one per character. Both are columns of `entities.csv` and
`characters.csv` (with `group_size` and `body_size`) and keys of `asset.extras.btg`, where `variants`
lists the other files in the same group.

### 4. Browse everything

```sh
python viewer/btg_viewer.py output
```

Opens a local, offline browser viewer at `http://127.0.0.1:8765/` with tabs for static meshes,
animated characters (with clip playback), textures and sounds, each as a searchable grid with
previews. Point it at whichever folder holds your extracted files (for example `output\converted`).
See [viewer/README.md](viewer/README.md) for details.

## Opening the models in Blender

1. **File → Import → glTF 2.0 (.glb/.gltf)** and pick a `.gltf` file.
2. For a rigged character, select the armature and open the **Action Editor** (Dope Sheet → Action
   Editor) or the **NLA Editor** to choose an animation clip.
3. Level geometry is in world space and can be large; press numpad `.` to frame it.

The output passes the [Khronos glTF validator](https://github.khronos.org/glTF-Validator/) with no
errors, so other glTF viewers work too.

## Features and roadmap

### Implemented

- [x] Reading the `.vol` / `.avl` archives and decompressing the BIGB wads inside them
- [x] Textures to PNG (~2,770), deduplicated across levels
- [x] Sound effects, music, ambience and cutscene audio to WAV (~680)
- [x] Plain-text config files from `general.vol` (level list, effects, controller maps)
- [x] Level geometry in world space, one glTF per level (63 levels)
- [x] Entity meshes in bind pose (~760: characters, Rahi, masks, props, skydomes)
- [x] Rigged characters with skeleton and skin weights (~170), alternate body variants split into separate files
- [x] Near-duplicate characters and entity meshes grouped as versions of one model
- [x] Cutscene cameras (25 rigs, 33 clips) as animated glTF cameras
- [x] Game text: UI, help text, objectives, Rahi descriptions and credits in all six languages
- [x] Collision meshes for each level (63), with surface types
- [x] Level entity placement: every strat placed in every level, with paths and trigger boxes
- [x] Animation clips with bone rotations and translations, including root motion
- [x] Transparency and blend modes (alpha blend, additive glow, alpha test) on every glTF material
- [x] Animated textures: every layer exported, with its scroll, rotation and blend op in the material extras
- [x] Water surfaces in every level that has water
- [x] Duplicate models merged across the whole game, with a list of every level that uses each one

### To do

- [ ] **Remaining skinned parts**: about a dozen rigid props (doors, iris panels, `Line10`, `little plank`, the closing-cutscene planets) that no skeleton fits yet; they are exported as static entities
- [ ] **Level scripts, particles, fog and sky settings**

Not possible: video, because the retail data has no Bink movies even though the game looks for `Movies\EA_Movie.bik`.

Format details, including what is still unknown, are in [docs/FORMAT_NOTES.md](docs/FORMAT_NOTES.md).
Pull requests for anything on the to-do list are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md).

## Repository layout

| Path | What |
|---|---|
| `tools/` | the three extractors above, plus `volt.ps1`, a PowerShell-only VOLT archive lister/unpacker |
| `viewer/` | local browser-based asset viewer (bundles three.js, MIT) |
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
