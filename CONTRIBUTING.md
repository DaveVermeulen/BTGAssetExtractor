# Contributing

Thanks for helping! Bug reports, format research and pull requests are all welcome.

## Reporting a problem

Open an issue with:

* the command you ran and the full output or error,
* your Python version (`python --version`) and operating system,
* which release of the game you have (retail CD, other region, etc.),
* for a broken model or texture, its output file name and the matching row in `index.csv`,
  `characters.csv` or `manifest.json`.

## Pull requests

* Keep each tool runnable as a single script: `bionicle_extract.py` uses the standard library only,
  and the model tools add nothing beyond numpy and Pillow. Talk to us in an issue first before
  adding a dependency.
* The tools must stay **read-only** on the game's `Data` folder.
* If you work out part of a file format, add it to [docs/FORMAT_NOTES.md](docs/FORMAT_NOTES.md)
  in the same pull request.
* Test against a full `Data` folder and mention the before/after output counts in the PR.

## Never commit game data

Do not add game files (`.vol`, `.avl`, `.exe`, …) or anything extracted from them (textures,
audio, models, screenshots of ripped assets in the repo) to issues or pull requests. The
`.gitignore` blocks the common cases; please double-check `git status` before committing.

By contributing you agree that your contribution is licensed under the [MIT License](LICENSE).
