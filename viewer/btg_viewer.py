#!/usr/bin/env python3
"""BTG Asset Viewer: browse the textures, sounds, models and animated characters you extracted.

Usage: python viewer/btg_viewer.py <output folder> [--port 8765] [--no-browser]
  e.g. python viewer/btg_viewer.py output

Python 3.8+, standard library only. Starts a small web server on 127.0.0.1 (this computer only),
indexes the folder you give it and opens the viewer in your browser. It reads your extracted files
and never changes them; the only thing it writes is a thumbnail cache in <output folder>/.viewer-cache/.

What it looks for anywhere under the folder:
  *.gltf / *.glb   models; files with animations or a skin go under "Animated", the rest "Static"
  *.png *.bmp ...  textures (images that a model references are left out, they are copies)
  *.wav            sounds
  index.csv, characters.csv, manifest.json, LEVELS.TXT   extra info (source file, level names)
"""
import sys, os, json, struct, csv, re, hashlib, threading, time, wave, array, argparse, webbrowser
import mimetypes, urllib.parse, subprocess, shutil
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web')
CACHE_DIR = '.viewer-cache'
IMAGE_EXT = {'.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp'}
MODEL_EXT = {'.gltf', '.glb'}
LEVEL_RE = re.compile(r'(\d{1,2}-\d{2})')
mimetypes.add_type('model/gltf+json', '.gltf')
mimetypes.add_type('model/gltf-binary', '.glb')
# Windows can map these to odd types in the registry; browsers refuse modules served as text/plain.
for _t, _e in (('text/javascript', '.js'), ('text/css', '.css'), ('text/html', '.html'), ('image/png', '.png'),
               ('audio/wav', '.wav'), ('application/json', '.json')):
    mimetypes.add_type(_t, _e)


# ---------------- indexing ----------------
def read_gltf_json(path):
    with open(path, 'rb') as f:
        if path.lower().endswith('.glb'):
            head = f.read(20)
            if head[:4] != b'glTF': return None
            ln = struct.unpack_from('<I', head, 12)[0]
            return json.loads(f.read(ln))
        return json.load(f)


def gltf_info(path, root):
    g = read_gltf_json(path)
    if g is None: return None, []
    acc = g.get('accessors', [])
    verts = tris = 0
    for m in g.get('meshes', []):
        for p in m.get('primitives', []):
            a = p.get('attributes', {}).get('POSITION')
            if a is not None and a < len(acc): verts += acc[a].get('count', 0)
            if p.get('mode', 4) == 4:
                i = p.get('indices')
                if i is not None and i < len(acc): tris += acc[i].get('count', 0) // 3
                elif a is not None and a < len(acc): tris += acc[a].get('count', 0) // 3
    size = os.path.getsize(path)
    base = os.path.dirname(path)
    for b in g.get('buffers', []):
        u = b.get('uri', '')
        if u and not u.startswith('data:'):
            p = os.path.join(base, urllib.parse.unquote(u))
            if os.path.isfile(p): size += os.path.getsize(p)
    images = []
    for im in g.get('images', []):
        u = im.get('uri', '')
        if u and not u.startswith('data:'):
            images.append(os.path.normpath(os.path.join(base, urllib.parse.unquote(u))))
    bones = sum(len(s.get('joints', [])) for s in g.get('skins', []))
    info = {
        'verts': verts, 'tris': tris, 'size': size, 'bones': bones,
        'textures': len(g.get('images', [])),
        'clips': [a.get('name') or 'clip %d' % i for i, a in enumerate(g.get('animations', []))],
    }
    # A model shared by several levels lists them all (the converter writes each unique mesh once).
    btg = ((g.get('asset') or {}).get('extras') or {}).get('btg') or {}
    if isinstance(btg, dict):
        for k in ('names', 'levels', 'sources'):
            v = btg.get(k)
            if isinstance(v, list): info['shared_' + k] = [str(x) for x in v if x]
    return info, images


def read_csvs(root_files):
    """index.csv / characters.csv rows keyed by absolute output path."""
    meta = {}
    for p in root_files:
        if os.path.basename(p).lower() not in ('index.csv', 'characters.csv'): continue
        base = os.path.dirname(p)
        try:
            with open(p, newline='', encoding='utf-8', errors='replace') as f:
                for row in csv.DictReader(f):
                    out = row.get('output')
                    if out: meta[os.path.normpath(os.path.join(base, out))] = row
        except (OSError, csv.Error):
            pass
    return meta


def read_level_names(root_files):
    names = {}
    for p in root_files:
        if os.path.basename(p).upper() != 'LEVELS.TXT': continue
        try:
            with open(p, encoding='latin1') as f:
                for line in f:
                    parts = line.rstrip('\r\n').split('\t')
                    if len(parts) >= 3 and LEVEL_RE.fullmatch(parts[0].strip()):
                        names[parts[0].strip()] = parts[2].strip()
        except OSError:
            pass
    return names


def read_manifest(root_files):
    """manifest.json from the texture/audio extractor, keyed by absolute path."""
    meta = {}
    for p in root_files:
        if os.path.basename(p) != 'manifest.json': continue
        base = os.path.dirname(p)
        try:
            with open(p, encoding='utf-8') as f: m = json.load(f)
        except (OSError, ValueError):
            continue
        for group in m.values() if isinstance(m, dict) else []:
            if not isinstance(group, list): continue
            for e in group:
                if isinstance(e, dict) and e.get('file'):
                    meta[os.path.normpath(os.path.join(base, e['file']))] = e
    return meta


def png_size(path):
    try:
        with open(path, 'rb') as f: h = f.read(26)
        if h[:8] == b'\x89PNG\r\n\x1a\n': return list(struct.unpack('>II', h[16:24]))
        if h[:2] == b'BM': return [struct.unpack_from('<i', h, 18)[0], abs(struct.unpack_from('<i', h, 22)[0])]
    except (OSError, struct.error):
        pass
    return None


def wav_info(path):
    try:
        with wave.open(path, 'rb') as w:
            return {'channels': w.getnchannels(), 'rate': w.getframerate(),
                    'duration': round(w.getnframes() / float(w.getframerate() or 1), 2)}
    except (OSError, wave.Error, EOFError):
        return {}


def level_of(*texts):
    for t in texts:
        m = LEVEL_RE.search(t or '')
        if m: return m.group(1)
    return ''


def build_index(root, log=print):
    t0 = time.time()
    cache = os.path.join(root, CACHE_DIR)
    files = []
    for d, dirs, fs in os.walk(root, followlinks=True):
        dirs[:] = sorted(x for x in dirs if not x.startswith('.'))
        files.extend(os.path.join(d, f) for f in sorted(fs))
    csvmeta = read_csvs(files)
    manifest = read_manifest(files)
    levels = read_level_names(files)
    rel = lambda p: os.path.relpath(p, root).replace(os.sep, '/')

    # Reading every glTF is the slow part, so remember what we found per file (size + mtime).
    cache_file = os.path.join(cache, 'index-cache.json')
    try:
        with open(cache_file, encoding='utf-8') as f: old = json.load(f)
        if old.get('version') != 2: old = {}
    except (OSError, ValueError):
        old = {}
    old_models, new_models = old.get('models', {}), {}

    models, textures, sounds, referenced = [], [], [], set()
    model_files = [p for p in files if os.path.splitext(p)[1].lower() in MODEL_EXT]
    for n, p in enumerate(model_files):
        if n and n % 500 == 0: log('  models: %d / %d' % (n, len(model_files)))
        r = rel(p)
        try:
            st = os.stat(p)
        except OSError:            # deleted while we were scanning (e.g. the converter is re-running)
            continue
        stamp = [st.st_size, int(st.st_mtime)]
        hit = old_models.get(r)
        if hit and hit.get('stamp') == stamp:
            info, imgs = hit['info'], [os.path.normpath(os.path.join(root, i)) for i in hit['imgs']]
        else:
            try:
                info, imgs = gltf_info(p, root)
            except (OSError, ValueError) as e:
                log('  skipped %s: %s' % (r, e)); continue
            if info is None: continue
        new_models[r] = {'stamp': stamp, 'info': info, 'imgs': [rel(i) for i in imgs]}
        referenced.update(imgs)
        row = csvmeta.get(os.path.normpath(p), {})
        folder = r.split('/')[-2] if '/' in r else ''
        name = os.path.splitext(os.path.basename(p))[0]
        if row.get('kind') == 'level' and row.get('title'):
            levels.setdefault(name, row['title'])
        animated = bool(info['clips']) or info['bones'] > 0
        info = dict(info)
        shared_levels, shared_sources = info.pop('shared_levels', []), info.pop('shared_sources', [])
        other_names = info.pop('shared_names', [])[1:]
        level = level_of(row.get('source'), name if folder == 'levels' else '')
        if shared_levels and level not in shared_levels: level = shared_levels[0]
        models.append(dict(info, path=r, images=[rel(i) for i in imgs], name=name.split('__')[0], id=name, folder=folder,
                           kind='animated' if animated else 'static',
                           source=row.get('source', '') or (shared_sources[0] if shared_sources else ''),
                           level=level, also_in=[l for l in shared_levels if l != level], other_names=other_names,
                           thumb=hashlib.sha1(('%s|%d|%d' % (r, st.st_size, int(st.st_mtime))).encode()).hexdigest()[:24]))

    for p in files:
        ext = os.path.splitext(p)[1].lower()
        if ext in IMAGE_EXT or ext == '.wav':
            if not os.path.isfile(p): continue
        r = rel(p)
        if r.startswith(CACHE_DIR + '/'): continue
        if ext in IMAGE_EXT and os.path.normpath(p) not in referenced:
            m = manifest.get(os.path.normpath(p), {})
            parts = r.split('/')
            textures.append({'path': r, 'name': os.path.splitext(parts[-1])[0],
                             'level': m.get('level') or (parts[-2] if len(parts) > 1 else ''),
                             'dims': m.get('size') or png_size(p), 'mode': m.get('mode', ''),
                             'source': m.get('source', ''), 'also_in': m.get('also_in', []),
                             'size': os.path.getsize(p)})
        elif ext == '.wav':
            m = manifest.get(os.path.normpath(p), {})
            parts = r.split('/')
            group = parts[-2] if len(parts) > 1 else ''
            lvl = parts[-3] if len(parts) > 2 and group in ('sfx', 'music_and_speech') else group
            w = ({'channels': m['channels'], 'rate': m['rate'], 'duration': m['seconds']}
                 if all(k in m for k in ('channels', 'rate', 'seconds')) else wav_info(p))
            sounds.append(dict(w, path=r, name=os.path.splitext(parts[-1])[0],
                               level=m.get('level') or lvl, group=group,
                               source=m.get('source', ''), also_in=m.get('also_in', []),
                               size=os.path.getsize(p)))

    try:
        os.makedirs(cache, exist_ok=True)
        with open(cache_file + '.tmp', 'w', encoding='utf-8') as f:
            json.dump({'version': 2, 'models': new_models}, f, separators=(',', ':'))
        os.replace(cache_file + '.tmp', cache_file)
    except OSError as e:
        log('  could not write the index cache: %s' % e)
    have = set(os.listdir(cache)) if os.path.isdir(cache) else set()
    for m in models: m['has_thumb'] = (m['thumb'] + '.png') in have
    log('Indexed %d models, %d textures, %d sounds in %.1fs' % (len(models), len(textures), len(sounds), time.time() - t0))
    return {'root': os.path.basename(os.path.abspath(root)), 'levels': levels,
            'models': models, 'textures': textures, 'sounds': sounds}


def wav_peaks(path, buckets=200):
    """Min/max pairs per bucket, scaled to -127..127, for drawing a waveform."""
    with wave.open(path, 'rb') as w:
        ch, sw, n = w.getnchannels(), w.getsampwidth(), w.getnframes()
        if sw != 2 or n == 0: return []
        step = max(1, n // (buckets * 64))          # sample sparsely on long files
        per = max(1, n // buckets)
        out = []
        for b in range(buckets):
            start = b * per
            if start >= n: break
            w.setpos(start)
            a = array.array('h', w.readframes(min(per, n - start)))
            if sys.byteorder == 'big': a.byteswap()
            s = a[::step * ch] if len(a) else a
            out.append([min(s) >> 8 if s else 0, max(s) >> 8 if s else 0])
        return out


# ---------------- server ----------------
class State:
    root = None
    index = None
    lock = threading.Lock()
    peaks = {}


def safe_join(base, relpath):
    p = os.path.abspath(os.path.join(base, *[x for x in relpath.replace('\\', '/').split('/') if x not in ('', '.')]))
    b = os.path.abspath(base)
    return p if (p == b or p.startswith(b + os.sep)) else None


class Handler(BaseHTTPRequestHandler):
    server_version = 'BTGViewer/1'

    def log_message(self, fmt, *args):
        pass

    def send_json(self, obj, code=200):
        body = json.dumps(obj, separators=(',', ':')).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, cache='no-cache'):
        if not path or not os.path.isfile(path):
            return self.send_error(404)
        size = os.path.getsize(path)
        ctype = mimetypes.guess_type(path)[0] or 'application/octet-stream'
        start, end = 0, size - 1
        rng = self.headers.get('Range')
        m = re.match(r'bytes=(\d*)-(\d*)$', rng or '')
        if m and size:
            if m.group(1): start = int(m.group(1)); end = int(m.group(2)) if m.group(2) else end
            elif m.group(2): start = max(0, size - int(m.group(2)))
            end = min(end, size - 1)
            if start > end:
                self.send_response(416); self.send_header('Content-Range', 'bytes */%d' % size); self.end_headers(); return
            self.send_response(206)
            self.send_header('Content-Range', 'bytes %d-%d/%d' % (start, end, size))
        else:
            self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(end - start + 1 if size else 0))
        self.send_header('Cache-Control', cache)
        self.end_headers()
        if self.command == 'HEAD' or not size: return
        with open(path, 'rb') as f:
            f.seek(start); left = end - start + 1
            try:
                while left > 0:
                    chunk = f.read(min(left, 1 << 20))
                    if not chunk: break
                    self.wfile.write(chunk); left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self.local_host(): return self.send_error(403)
        url = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(url.path)
        q = urllib.parse.parse_qs(url.query)
        if path == '/api/index':
            with State.lock:
                if State.index is None or 'refresh' in q:
                    State.index = build_index(State.root)
                    State.peaks.clear()
            return self.send_json(State.index)
        if path == '/api/peaks':
            p = safe_join(State.root, q.get('path', [''])[0])
            if not p or not p.lower().endswith('.wav') or not os.path.isfile(p): return self.send_error(404)
            if p not in State.peaks:
                try: State.peaks[p] = wav_peaks(p)
                except (OSError, wave.Error, EOFError): State.peaks[p] = []
            return self.send_json(State.peaks[p])
        if path.startswith('/api/thumb/'):
            key = path[len('/api/thumb/'):].replace('.png', '')
            if not re.fullmatch(r'[0-9a-f]{24}', key): return self.send_error(404)
            return self.send_file(os.path.join(State.root, CACHE_DIR, key + '.png'), 'max-age=31536000, immutable')
        if path.startswith('/files/'):
            return self.send_file(safe_join(State.root, path[len('/files/'):]))
        if path == '/': path = '/index.html'
        return self.send_file(safe_join(WEB, path.lstrip('/')))

    def local_host(self):
        # A page on another site that rebinds its DNS name to 127.0.0.1 still sends its own name as Host.
        host = self.headers.get('Host', '')
        return urllib.parse.urlsplit('//' + host).hostname in ('127.0.0.1', 'localhost')

    def same_origin(self):
        # Browsers always send Origin on POST; refuse requests from any other web page.
        origin = self.headers.get('Origin', '')
        return self.local_host() and bool(origin) and urllib.parse.urlsplit(origin).netloc == self.headers.get('Host', '')

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == '/api/reveal':
            return self.reveal()
        key = path[len('/api/thumb/'):] if path.startswith('/api/thumb/') else ''
        # Only accept thumbnails from the viewer page itself.
        if not re.fullmatch(r'[0-9a-f]{24}', key) or not self.same_origin():
            return self.send_error(403)
        n = int(self.headers.get('Content-Length') or 0)
        if not 0 < n <= 2 << 20: return self.send_error(413)
        data = self.rfile.read(n)
        if data[:8] != b'\x89PNG\r\n\x1a\n': return self.send_error(400)
        d = os.path.join(State.root, CACHE_DIR)
        os.makedirs(d, exist_ok=True)
        tmp = os.path.join(d, key + '.tmp')
        with open(tmp, 'wb') as f: f.write(data)
        os.replace(tmp, os.path.join(d, key + '.png'))
        self.send_response(204); self.end_headers()


    def reveal(self):
        """Show a file from the output folder in File Explorer / Finder / the file manager."""
        if not self.same_origin() or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.send_error(403)
        n = int(self.headers.get('Content-Length') or 0)
        if not 0 < n <= 4096: return self.send_error(413)
        try:
            rel = json.loads(self.rfile.read(n)).get('path', '')
        except (ValueError, AttributeError):
            return self.send_error(400)
        p = safe_join(State.root, rel) if isinstance(rel, str) else None
        if not p or not os.path.exists(p): return self.send_error(404)
        try:
            reveal_in_file_manager(p)
        except (OSError, RuntimeError) as e:
            return self.send_json({'error': str(e)}, 500)
        self.send_response(204); self.end_headers()


def reveal_in_file_manager(p):
    if sys.platform == 'win32':
        # explorer.exe parses its own command line; Windows paths can't contain quotes.
        subprocess.Popen('explorer /select,"%s"' % os.path.normpath(p))
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', '-R', p])
    else:
        uri = 'file://' + urllib.parse.quote(p)
        if shutil.which('dbus-send'):
            r = subprocess.run(['dbus-send', '--session', '--print-reply', '--dest=org.freedesktop.FileManager1',
                                '/org/freedesktop/FileManager1', 'org.freedesktop.FileManager1.ShowItems',
                                'array:string:' + uri, 'string:'], capture_output=True, timeout=5)
            if r.returncode == 0: return
        if not shutil.which('xdg-open'): raise RuntimeError('no file manager found')
        subprocess.Popen(['xdg-open', os.path.dirname(p)])


def main():
    ap = argparse.ArgumentParser(description='Browse extracted BIONICLE: The Game assets in your web browser.')
    ap.add_argument('folder', help='your output folder (the one holding textures/, audio/ and models/)')
    ap.add_argument('--port', type=int, default=8765)
    ap.add_argument('--no-browser', action='store_true', help="don't open a browser window")
    a = ap.parse_args()
    if not os.path.isdir(a.folder):
        sys.exit('Not a folder: %s' % a.folder)
    State.root = os.path.abspath(a.folder)
    print('Indexing %s ...' % State.root)
    State.index = build_index(State.root)
    # On Windows SO_REUSEADDR lets a second server bind a port that is already in use.
    ThreadingHTTPServer.allow_reuse_address = sys.platform != 'win32'
    srv = None
    for port in range(a.port, a.port + 20):
        try:
            srv = ThreadingHTTPServer(('127.0.0.1', port), Handler); break
        except OSError:
            continue
    if srv is None: sys.exit('No free port near %d' % a.port)
    url = 'http://127.0.0.1:%d/' % srv.server_address[1]
    print('Viewer running at %s  (this computer only; press Ctrl+C to stop)' % url)
    if not a.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')


if __name__ == '__main__':
    main()
