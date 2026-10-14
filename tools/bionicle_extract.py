#!/usr/bin/env python3
"""BIONICLE (PC, 2003) texture and audio extractor. Python 3.8+, standard library only.

Usage: python bionicle_extract.py <path to BIONICLE\\Data> <output folder> [level,level,...]
  e.g. python bionicle_extract.py "C:\\Games\\BIONICLE\\Data" extracted
       python bionicle_extract.py Data out 10,22      (only 10.vol/10.avl and 22.vol/22.avl)

Reads the game's .vol/.avl archives (never writes to them) and writes:
  <out>/textures/<level>/*.png        embedded TGA textures, plus general.vol DDS/BMP skies
  <out>/audio/<level>/sfx/*.wav       mono sound bank entries (Xbox IMA ADPCM -> 16-bit PCM)
  <out>/audio/<level>/music_and_speech/*.wav   stereo streams
  <out>/other/general/*               text/config files from general.vol
  <out>/other/text/game_text.csv      every line of game text in six languages (also as .json)
  <out>/manifest.json                 every output with its source and duplicate locations
  <out>/texture_index.json            (wad, texture record offset) -> png, for binding textures to models

Formats (all little-endian):
  VOLT archive : "VOLT", u32 ver=2, u32 count, u32 recblock; count*{u32 hash,u32 1,u32 recoff};
                 records {u32 offset,u32 0,u32 size,u32 0,char name[] NUL}
  BIGB wad     : 0x180-byte header; 0x78 sfx bank size, 0x7C stream size, 0x80/0x84 unpacked
                 sizes A/B, 0x88/0x8C packed sizes A/B; packed data A then B starts at 0x190.
  Compression  : c<0x40 -> c+1 literals; 0x40..0x7F -> repeat next byte (c&0x3F)+2 times;
                 else big-endian int16 w=(c<<8|next): copy (w&15)+2 bytes from -(w>>4)+1 back.
  Texture      : record [0x00545C6C][w][h][0][ptr][size]; ptr is a whole TGA file.
  Audio        : RIFF/WAVE (sfx) and RIFF/WAVS (stream) headers in the wad, chunks fmt/fact/
                 name/strm(offset,size). Data in <level>.PCA: sfx bank at 0, streams at
                 roundup(bank size, 0x800). Codec 0x69 Xbox IMA ADPCM, 36 bytes/64 samples/channel.
"""
import sys, os, struct, re, io, hashlib, json, wave, zlib, csv

# ---------------- VOLT archives ----------------
def volt_list(path):
    with open(path, 'rb') as f:
        head = f.read(16)
        if head[:4] != b'VOLT': raise ValueError(path + ' is not a VOLT archive')
        ver, cnt, nsz = struct.unpack_from('<3I', head, 4)
        tab = f.read(cnt * 12 + nsz)
    out = []
    for i in range(cnt):
        _, _, ro = struct.unpack_from('<3I', tab, i * 12)
        q = cnt * 12 + ro
        off, _, size, _ = struct.unpack_from('<4I', tab, q)
        name = tab[q + 16:tab.index(b'\0', q + 16)].decode('latin1')
        out.append((name, off, size))
    return out

# ---------------- BIGB decompression ----------------
def argz(src, cap):
    out = bytearray(); i = 0; n = len(src)
    while i < n and len(out) < cap:
        c = src[i]
        if c < 0x40:
            out += src[i + 1:i + 2 + c]; i += 2 + c
        elif c < 0x80:
            if i + 1 >= n: break
            out += bytes((src[i + 1],)) * ((c & 0x3F) + 2); i += 2
        else:
            if i + 1 >= n: break
            w = (c << 8) | src[i + 1]; w -= 0x10000          # c>=0x80 so always negative
            dist = -(w >> 4) + 1; ln = (w & 15) + 2; i += 2
            s = len(out) - dist
            if s >= 0 and dist >= ln:
                out += out[s:s + ln]
            else:                                             # overlapping or before start
                for k in range(ln):
                    out.append(out[s + k] if s + k >= 0 else 0)
    return bytes(out[:cap])

WAD_DATA = 0x190    # packed data starts after the build command line (0x90..0x190), not at the 0x180 header size

def unwad(b):
    if len(b) < WAD_DATA or b[:4] != b'BIGB': return None
    bank, streams, ua, ub, pa, pb = struct.unpack_from('<6I', b, 0x78)
    if not ua: return None
    return argz(b[WAD_DATA:WAD_DATA + pa], ua), bank

def unwad_relocs(b):
    """Offsets in the unpacked wad that hold pointers (section B, the relocation stream: u32 list where
    a value with bit 31 set starts a group and the values after it are pointer offsets)."""
    ua, ub, pa, pb = struct.unpack_from('<4I', b, 0x80)
    if not ub: return set()
    r = argz(b[WAD_DATA + pa:WAD_DATA + pa + pb], ub)
    return {v for v in struct.unpack_from('<%dI' % (len(r) // 4), r) if not v & 0x80000000}

# ---------------- game text ----------------
LANGS = ('english', 'french', 'german', 'spanish', 'italian', 'danish')
GLYPHS = {i: '[button %d]' % i for i in range(1, 0x1f)}   # controller-button icons drawn inline
GLYPHS[0x1f] = '\n'                                       # line break

def game_text(d, ptrs):
    """Text records in an unpacked .PCS: 8 consecutive pointers, the first six to the same line in
    English, French, German, Spanish, Italian and Danish (UTF-8, NUL-terminated), the last two 0.
    Scripts point at the record. Yields the six strings with control codes made readable."""
    def text(v):
        e = d.find(b'\0', v, v + 4000)
        if e < 0: return None
        try: t = d[v:e].decode('utf8')
        except UnicodeDecodeError: return None
        if sum(ord(c) < 32 for c in t) > max(2, len(t) // 8): return None
        return ''.join(GLYPHS.get(ord(c), c) if ord(c) < 32 else c for c in t)
    for p in sorted(ptrs):
        if p - 4 in ptrs or not all(p + 4 * k in ptrs for k in range(1, 6)) or p + 32 > len(d): continue
        v = struct.unpack_from('<8I', d, p)
        if v[6] or v[7] or max(v[:6]) >= len(d): continue
        t = [text(x) for x in v[:6]]
        if None in t or sum(bool(re.search('[A-Za-z]{2}', x)) for x in t) < 4: continue
        yield t

# ---------------- PNG writer ----------------
def write_png(path, w, h, rows, channels):
    """rows: list of bytes, top to bottom, each w*channels long (RGB or RGBA)."""
    ctype = 6 if channels == 4 else 2
    raw = b''.join(b'\0' + r for r in rows)
    def chunk(t, d): return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, ctype, 0, 0, 0))
                + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))

def _bgr_to_rgb(px, ch):
    a = bytearray(px)
    a[0::ch], a[2::ch] = px[2::ch], px[0::ch]
    return bytes(a)

def tga_to_png(t, path):
    idl, cmt, it, cs, cl, cd, xo, yo, w, h, bpp, desc = struct.unpack_from('<BBBHHBHHHHBB', t, 0)
    p = 18 + idl
    if it == 1 and cmt == 1 and bpp == 8:
        ce = cd // 8
        if ce not in (3, 4): raise ValueError('unsupported palette depth %d' % cd)
        pal = _bgr_to_rgb(t[p:p + cl * ce], ce); p += cl * ce
        entries = [pal[k * ce:(k + 1) * ce] for k in range(cl)]
        idx = t[p:p + w * h]
        lut = [entries[min(max(v - cs, 0), cl - 1)] for v in range(256)]
        px = b''.join(lut[v] for v in idx); ch = ce
    elif it == 2 and bpp in (24, 32):
        ch = bpp // 8; px = _bgr_to_rgb(t[p:p + w * h * ch], ch)
    else:
        raise ValueError('unsupported TGA type %d / %d bpp' % (it, bpp))
    if ch == 4 and all(a == 255 for a in px[3::4]):      # opaque: drop alpha
        px = b''.join(px[k:k + 3] for k in range(0, len(px), 4)); ch = 3
    rows = [px[r * w * ch:(r + 1) * w * ch] for r in range(h)]
    if not desc & 0x20: rows.reverse()                       # TGA default is bottom-up
    write_png(path, w, h, rows, ch)
    return 'RGBA' if ch == 4 else 'RGB'

# ---------------- DDS / BMP (general.vol) ----------------
def _c565(c): return (((c >> 11) & 31) * 255 // 31, ((c >> 5) & 63) * 255 // 63, (c & 31) * 255 // 31)

def dds_to_png(b, path):
    h, w = struct.unpack_from('<II', b, 12)
    pf_flags, fourcc, bits, rm, gm, bm, am = struct.unpack_from('<I4s5I', b, 80)
    data = b[128:]; px = bytearray(w * h * 4)
    if pf_flags & 4 and fourcc in (b'DXT1', b'DXT3', b'DXT5'):
        bs = 8 if fourcc == b'DXT1' else 16; q = 0
        for by in range(0, h, 4):
            for bx in range(0, w, 4):
                blk = data[q:q + bs]; q += bs
                alpha = [255] * 16
                if fourcc == b'DXT3':
                    a64 = int.from_bytes(blk[:8], 'little'); alpha = [((a64 >> (4 * k)) & 15) * 17 for k in range(16)]
                elif fourcc == b'DXT5':
                    a0, a1 = blk[0], blk[1]; ab = int.from_bytes(blk[2:8], 'little')
                    al = [a0, a1] + ([((6 - k) * a0 + (k + 1) * a1) // 7 for k in range(6)] if a0 > a1 else
                                     [((4 - k) * a0 + (k + 1) * a1) // 5 for k in range(4)] + [0, 255])
                    alpha = [al[(ab >> (3 * k)) & 7] for k in range(16)]
                cb = blk[bs - 8:]
                c0, c1, bits32 = struct.unpack('<HHI', cb)
                p0, p1 = _c565(c0), _c565(c1)
                if c0 > c1 or fourcc != b'DXT1':
                    cols = [p0 + (255,), p1 + (255,), tuple((2 * x + y) // 3 for x, y in zip(p0, p1)) + (255,),
                            tuple((x + 2 * y) // 3 for x, y in zip(p0, p1)) + (255,)]
                else:
                    cols = [p0 + (255,), p1 + (255,), tuple((x + y) // 2 for x, y in zip(p0, p1)) + (255,), (0, 0, 0, 0)]
                for k in range(16):
                    x, y = bx + (k & 3), by + (k >> 2)
                    if x < w and y < h:
                        r, g, bb, a = cols[(bits32 >> (2 * k)) & 3]
                        o = (y * w + x) * 4; px[o:o + 4] = bytes((r, g, bb, a * alpha[k] // 255))
    elif pf_flags & 0x40 and bits in (24, 32):
        ch = bits // 8
        def sh(m): return (m & -m).bit_length() - 1 if m else 0
        for k in range(w * h):
            v = int.from_bytes(data[k * ch:(k + 1) * ch], 'little')
            px[k * 4:k * 4 + 4] = bytes(((v & rm) >> sh(rm), (v & gm) >> sh(gm), (v & bm) >> sh(bm),
                                         ((v & am) >> sh(am)) if (pf_flags & 1 and am) else 255))
    else:
        raise ValueError('unsupported DDS pixel format %r' % fourcc)
    ch = 4
    if all(a == 255 for a in px[3::4]):
        px = b''.join(bytes(px[k:k + 3]) for k in range(0, len(px), 4)); ch = 3
    write_png(path, w, h, [bytes(px[r * w * ch:(r + 1) * w * ch]) for r in range(h)], ch)
    return 'RGBA' if ch == 4 else 'RGB'

def bmp_to_png(b, path):
    off = struct.unpack_from('<I', b, 10)[0]
    w, h, _, bpp, comp = struct.unpack_from('<iiHHI', b, 18)
    if comp != 0 or bpp not in (8, 24, 32): raise ValueError('unsupported BMP (%d bpp, compression %d)' % (bpp, comp))
    stride = (w * bpp // 8 + 3) & ~3; rows = []
    pal = None
    if bpp == 8:
        hsz = struct.unpack_from('<I', b, 14)[0]; ncol = struct.unpack_from('<I', b, 46)[0] or 256
        pal = [bytes((b[14 + hsz + 4 * k + 2], b[14 + hsz + 4 * k + 1], b[14 + hsz + 4 * k])) for k in range(ncol)]
    for r in range(abs(h)):
        line = b[off + r * stride: off + r * stride + w * bpp // 8]
        if bpp == 8: rows.append(b''.join(pal[v] for v in line))
        else: rows.append(b''.join(bytes((line[k + 2], line[k + 1], line[k])) for k in range(0, len(line), bpp // 8)))
    if h > 0: rows.reverse()
    write_png(path, w, abs(h), rows, 3); return 'RGB'

# ---------------- Xbox IMA ADPCM ----------------
STEPS = [7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658, 724, 796, 876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327, 3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442, 11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767]
IDX = [-1, -1, -1, -1, 2, 4, 6, 8]
# DIFF[idx][nibble] precomputed so the inner loop is a table lookup
DIFF = []
for st in STEPS:
    row = []
    for nb in range(16):
        d = st >> 3
        if nb & 1: d += st >> 2
        if nb & 2: d += st >> 1
        if nb & 4: d += st
        row.append(-d if nb & 8 else d)
    DIFF.append(row)
NEXT = [[min(max(i + IDX[nb & 7], 0), 88) for nb in range(16)] for i in range(89)]

def xbox_adpcm(raw, ch, nsamp):
    """Returns interleaved little-endian int16 PCM bytes, nsamp frames at most."""
    from array import array
    bs = 36 * ch; nblocks = len(raw) // bs
    chans = [array('h') for _ in range(ch)]
    for bi in range(nblocks):
        p = bi * bs
        for c in range(ch):
            pred = struct.unpack_from('<h', raw, p + 4 * c)[0]; idx = min(raw[p + 4 * c + 2], 88)
            outc = chans[c]
            for g in range(8):
                q = p + 4 * ch + (g * ch + c) * 4
                for byte in raw[q:q + 4]:
                    for nb in (byte & 15, byte >> 4):
                        pred += DIFF[idx][nb]
                        if pred > 32767: pred = 32767
                        elif pred < -32768: pred = -32768
                        idx = NEXT[idx][nb]
                        outc.append(pred)
    n = min(nsamp, len(chans[0]))
    if ch == 1:
        out = chans[0][:n]
    else:
        out = array('h', bytes(2 * n * ch))
        for c in range(ch): out[c::ch] = chans[c][:n]
    if sys.byteorder != 'little': out.byteswap()
    return out.tobytes(), n

# ---------------- wad scanning ----------------
def riff_entries(d):
    for m in re.finditer(b'RIFF', d):
        p = m.start()
        if d[p + 8:p + 11] != b'WAV': continue
        kind = d[p + 8:p + 12]; sz = struct.unpack_from('<I', d, p + 4)[0]
        q = p + 12; info = {}
        while q + 8 <= p + 8 + sz and q + 8 <= len(d):
            cid = d[q:q + 4]; cs = struct.unpack_from('<I', d, q + 4)[0]; info[cid] = d[q + 8:q + 8 + cs]; q += 8 + cs
        if b'fmt ' in info and b'strm' in info: yield kind, info

def safe(s): return re.sub(r'[^\w.\- ]', '_', s).strip() or 'unnamed'

def main(data, out, only=None):
    texdir = os.path.join(out, 'textures'); auddir = os.path.join(out, 'audio')
    os.makedirs(texdir, exist_ok=True); os.makedirs(auddir, exist_ok=True)
    man = {'textures': [], 'audio': [], 'other': [], 'failures': []}
    tex_index = []; seen_tex = {}; seen_hdr = set(); seen_raw = {}; tex_count = {}; texts = {}
    vols = sorted(f for f in os.listdir(data) if f.lower().endswith('.vol'))
    for vf in vols:
        lv = vf[:-4]
        if only and lv not in only: continue
        vp = os.path.join(data, vf); ap = os.path.join(data, lv + '.avl')
        avl = {n: (o, s) for n, o, s in volt_list(ap)} if os.path.exists(ap) else {}
        fv = open(vp, 'rb'); fa = open(ap, 'rb') if avl else None
        for n, off, sz in sorted(volt_list(vp)):
            fv.seek(off); b = fv.read(sz); ext = n.rsplit('.', 1)[-1].upper(); stem = n.rsplit('.', 1)[0]
            if lv.lower() == 'general':
                try:
                    if ext in ('DDS', 'BMP'):
                        os.makedirs(os.path.join(texdir, 'general'), exist_ok=True)
                        p = os.path.join(texdir, 'general', stem + '.png')
                        mode = dds_to_png(b, p) if ext == 'DDS' else bmp_to_png(b, p)
                        man['textures'].append({'file': os.path.relpath(p, out), 'source': vf + '/' + n, 'mode': mode})
                    else:
                        os.makedirs(os.path.join(out, 'other', 'general'), exist_ok=True)
                        with open(os.path.join(out, 'other', 'general', n), 'wb') as f: f.write(b)
                        man['other'].append(vf + '/' + n)
                except Exception as ex:
                    man['failures'].append({'source': vf + '/' + n, 'error': repr(ex)})
                continue
            if ext not in ('PCS', 'PCSI', 'PCM'): continue
            r = unwad(b)
            if r is None: continue
            d, bank_size = r
            for t in game_text(d, unwad_relocs(b)):
                e = texts.setdefault(tuple(t), {'levels': [], 'sources': []})
                if stem not in e['levels']: e['levels'].append(stem)
                if vf + '/' + n not in e['sources']: e['sources'].append(vf + '/' + n)
            for m in re.finditer(re.escape(b'\x6c\x5c\x54\x00'), d):
                T = m.start()
                try:
                    w, h, z, ptr, tsz = struct.unpack_from('<5I', d, T + 4)
                    t = d[ptr:ptr + tsz]
                    if len(t) != tsz or tsz < 18 or struct.unpack_from('<HH', t, 12) != (w, h): continue
                    hsh = hashlib.sha1(t).hexdigest()[:12]
                    rec = {'wad': vf + '/' + n, 'record_offset': T, 'image_offset': ptr, 'width': w, 'height': h, 'sha1_12': hsh}
                    tex_index.append(rec)
                    if hsh in seen_tex: seen_tex[hsh]['also_in'].append(vf + '/' + n); rec['png'] = seen_tex[hsh]['file']; continue
                    os.makedirs(os.path.join(texdir, stem), exist_ok=True)
                    i = tex_count.get(stem, 0); tex_count[stem] = i + 1
                    p = os.path.join(texdir, stem, '%s_%03d_%dx%d_%s.png' % (stem, i, w, h, hsh))
                    mode = tga_to_png(t, p)
                    e = {'file': os.path.relpath(p, out), 'source': '%s/%s@0x%x' % (vf, n, ptr), 'size': [w, h], 'mode': mode, 'level': stem, 'also_in': []}
                    seen_tex[hsh] = e; man['textures'].append(e); rec['png'] = e['file']
                except Exception as ex:
                    man['failures'].append({'source': '%s/%s@0x%x' % (vf, n, T), 'error': repr(ex)})
            pca = stem + '.PCA'
            for kind, info in riff_entries(d):
                name = info.get(b'name', b'').split(b'\0')[0].decode('latin1') or 'unnamed.wav'
                tag, ch, rate = struct.unpack_from('<HHI', info[b'fmt '])
                so, ssz = struct.unpack_from('<II', info[b'strm'])
                nsamp = struct.unpack_from('<I', info[b'fact'])[0] if b'fact' in info else ssz // (36 * ch) * 64
                base = ((bank_size + 0x7FF) & ~0x7FF) if kind == b'WAVS' else 0
                if (pca, base + so, ssz) in seen_hdr: continue
                seen_hdr.add((pca, base + so, ssz))
                try:
                    if pca not in avl: raise ValueError(pca + ' not found in ' + lv + '.avl')
                    po, ps = avl[pca]
                    if base + so + ssz > ps: raise ValueError('data range past end of ' + pca)
                    if tag != 0x69: raise ValueError('unsupported codec 0x%x' % tag)
                    fa.seek(po + base + so); raw = fa.read(ssz)
                    if any(raw[4 * c + 3] != 0 or raw[4 * c + 2] > 88 for c in range(ch)):
                        raise ValueError('data does not look like Xbox ADPCM at the expected offset')
                    ah = hashlib.sha1(raw).hexdigest()
                    if ah in seen_raw: seen_raw[ah]['also_in'].append(lv + '.avl/' + pca); continue
                    pcm, ns = xbox_adpcm(raw, ch, nsamp)
                    od = os.path.join(auddir, stem, 'music_and_speech' if kind == b'WAVS' else 'sfx'); os.makedirs(od, exist_ok=True)
                    fs = safe(name.rsplit('.', 1)[0]); p = os.path.join(od, fs + '.wav'); i = 2
                    while os.path.exists(p): p = os.path.join(od, '%s_%d.wav' % (fs, i)); i += 1
                    with wave.open(p, 'wb') as wv:
                        wv.setnchannels(ch); wv.setsampwidth(2); wv.setframerate(rate); wv.writeframes(pcm)
                    e = {'file': os.path.relpath(p, out), 'name': name, 'source': '%s.avl/%s@0x%x' % (lv, pca, base + so),
                         'channels': ch, 'rate': rate, 'seconds': round(ns / rate, 2), 'loop': b'wsmp' in info, 'also_in': []}
                    man['audio'].append(e); seen_raw[ah] = e
                except Exception as ex:
                    man['failures'].append({'source': '%s/%s -> %s' % (vf, n, name), 'error': repr(ex)})
            print('%s %s: %d textures, %d sounds, %d failures so far' % (vf, n, len(man['textures']), len(man['audio']), len(man['failures'])), flush=True)
        fv.close()
        if fa: fa.close()
    if texts:
        td = os.path.join(out, 'other', 'text'); os.makedirs(td, exist_ok=True)
        rows = [dict(zip(LANGS, t), levels=e['levels'], sources=e['sources']) for t, e in texts.items()]
        with open(os.path.join(td, 'game_text.json'), 'w', encoding='utf-8') as f: json.dump(rows, f, indent=1, ensure_ascii=False)
        with open(os.path.join(td, 'game_text.csv'), 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.writer(f); w.writerow(LANGS + ('levels',))
            for r in rows: w.writerow([r[k] for k in LANGS] + [';'.join(r['levels'])])
        man['other'].append('other/text/game_text.json (%d lines)' % len(rows))
    with open(os.path.join(out, 'manifest.json'), 'w') as f: json.dump(man, f, indent=1)
    with open(os.path.join(out, 'texture_index.json'), 'w') as f:
        json.dump({'note': 'Every texture record in every unpacked wad. record_offset = offset of the texture record '
                   '([0x00545C6C][w][h][0][ptr][size]) in the unpacked wad (section A, pre-relocation); models point at '
                   'this. png = de-duplicated output file relative to the output folder.', 'records': tex_index}, f, indent=0)
    return man

if __name__ == '__main__':
    if len(sys.argv) < 3: print(__doc__); sys.exit(1)
    m = main(sys.argv[1], sys.argv[2], sys.argv[3].split(',') if len(sys.argv) > 3 else None)
    print('done: %d textures, %d sounds, %d other files, %d failures' % (len(m['textures']), len(m['audio']), len(m['other']), len(m['failures'])))
