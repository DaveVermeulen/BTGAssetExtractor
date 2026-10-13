# BTGAssetExtractor

Tools for extracting assets from **BIONICLE: The Game** (2003, PC).

- Game install (read-only source, never modified): `C:\Program Files (x86)\LEGO Interactive\BIONICLE`
- `tools/`  extraction and conversion scripts (committed)
- `docs/`   file format notes (committed)
- `output/raw/`        files unpacked from the game archives (git-ignored)
- `output/converted/`  assets converted to modern formats (git-ignored)
- `scratch/`           throwaway experiments (git-ignored)

All tools open game files read-only and write only under `output/`.
