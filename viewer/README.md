# BTG Asset Viewer

A browser-based viewer for the files the extractor tools write. It has four tabs:

* **Static meshes**: entity meshes and whole levels, with rendered thumbnails. Click one to orbit, zoom and switch the display between textured, wireframe on grey and wireframe lines only.
* **Animated meshes**: rigged characters. Pick any animation clip, play, pause, change speed, scrub the timeline,
  show the skeleton, or turn on *Follow* to keep the camera on characters whose clips move them across the level.
* **Textures**: every PNG in a grid. Click one for a large view with zoom, background and alpha options.
* **Sounds**: every WAV with a waveform. Play, pause and click the waveform to seek.

Each tab has a search box, a level filter (with the level names from `LEVELS.TXT`) and sorting.
Use the arrow keys to step through items in the large view and `Esc` to close it.

## Run it

Extract first (see the main README), then point the viewer at your output folder:

```sh
python viewer/btg_viewer.py output
```

Your browser opens at `http://127.0.0.1:8765/`. Press `Ctrl+C` in the terminal to stop it.
Options: `--port 9000` to use another port, `--no-browser` to not open a browser window.

It needs only Python 3.8 or newer; no packages to install and no internet connection.
Any recent Chrome, Edge or Firefox works.

The viewer finds files anywhere under the folder you give it, so these layouts all work:

```
output/textures, output/audio, output/models/...    (the layout in the main README)
output/converted/...                                (any other folder names)
```

Models with animation clips or a skeleton go under *Animated meshes*; the rest are *Static meshes*.
PNGs that a model uses as its texture are left out of the *Textures* tab, because they are copies.

## Thumbnails and the cache

Model thumbnails are rendered in your browser the first time a card scrolls into view, then saved to
`<output folder>/.viewer-cache/` so they load instantly next time. *Render all thumbnails* renders every
model in the current list in one go. The same folder holds `index-cache.json`, which makes later starts fast.
Delete `.viewer-cache` at any time to start fresh.

## Privacy and legal

* The server listens on `127.0.0.1` only, so nothing outside your computer can reach it.
* It only reads the folder you give it, never changes your extracted files, and uploads nothing.
  The only thing it writes is the `.viewer-cache` folder inside your output folder.
* No game files or extracted assets are part of the viewer. Don't host it on a public server
  with your extracted assets: they remain the property of their owners.

three.js (MIT License, `web/vendor/three/`) is included so the viewer works offline.
