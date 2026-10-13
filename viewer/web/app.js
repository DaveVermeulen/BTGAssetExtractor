import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fileUrl = (p) => '/files/' + p.split('/').map(encodeURIComponent).join('/');
const fmtSize = (n) => n > 1 << 20 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB';
const fmtTime = (s) => { s = Math.max(0, s || 0); const m = Math.floor(s / 60); return m + ':' + (s - m * 60).toFixed(1).padStart(4, '0'); };
const fmtNum = (n) => (n || 0).toLocaleString();
const PAGE = 120;

const TABS = {
  static: { label: 'static meshes', chips: [['all', 'All'], ['entities', 'Entities'], ['levels', 'Levels']] },
  animated: { label: 'animated meshes', chips: [] },
  textures: { label: 'textures', chips: [] },
  sounds: { label: 'sounds', chips: [['all', 'All'], ['sfx', 'Effects & voices'], ['music_and_speech', 'Music & speech']] },
};

const state = { tab: 'static', q: '', level: '', chip: 'all', sort: 'name', list: [], shown: 0 };
let DATA = null;

// ---------------------------------------------------------------- data
async function loadIndex(refresh) {
  $('#status').textContent = 'Indexing…';
  const r = await fetch('/api/index' + (refresh ? '?refresh=1' : ''));
  DATA = await r.json();
  DATA.static = DATA.models.filter((m) => m.kind === 'static');
  DATA.animated = DATA.models.filter((m) => m.kind === 'animated');
  for (const t of ['static', 'animated', 'textures', 'sounds']) {
    for (const it of DATA[t]) it._search = [it.name, it.path, it.source, it.level, DATA.levels[it.level], ...(it.clips || [])].join(' ').toLowerCase();
    document.querySelector(`[data-tab=${t}] .count`).textContent = fmtNum(DATA[t].length);
  }
  $('#rootName').textContent = DATA.root;
  $('#status').textContent = '';
}

function displayName(it) { return it.folder === 'levels' && DATA.levels[it.name] ? DATA.levels[it.name] : it.name; }
function levelLabel(l) { return l ? (DATA.levels[l] ? `${l} · ${DATA.levels[l]}` : l) : ''; }

function levelKey(l) { const m = /^(\d+)-(\d+)$/.exec(l || ''); return m ? +m[1] * 1000 + +m[2] : 1e9; }

function filtered() {
  const q = state.q.trim().toLowerCase().split(/\s+/).filter(Boolean);
  let list = DATA[state.tab].filter((it) =>
    (!state.level || it.level === state.level) &&
    (state.chip === 'all' || !TABS[state.tab].chips.length || it.folder === state.chip || it.group === state.chip) &&
    q.every((w) => it._search.includes(w)));
  const by = {
    name: (a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }) || a.path.localeCompare(b.path),
    level: (a, b) => levelKey(a.level) - levelKey(b.level) || a.name.localeCompare(b.name, undefined, { numeric: true }),
    size: (a, b) => b.size - a.size,
    detail: (a, b) => detail(b) - detail(a),
  };
  return list.sort(by[state.sort] || by.name);
}
function detail(it) {
  if (it.tris !== undefined) return it.tris;
  if (it.dims) return it.dims[0] * it.dims[1];
  return it.duration || 0;
}

// ---------------------------------------------------------------- toolbar / routing
function readHash() {
  const h = new URLSearchParams(location.hash.slice(1));
  if (TABS[h.get('tab')]) state.tab = h.get('tab');
  state.q = h.get('q') || ''; state.level = state.pickedLevel = h.get('level') || ''; state.chip = h.get('f') || 'all'; state.sort = h.get('sort') || 'name';
}
function writeHash() {
  const h = new URLSearchParams({ tab: state.tab });
  if (state.q) h.set('q', state.q); if (state.level) h.set('level', state.level);
  if (state.chip !== 'all') h.set('f', state.chip); if (state.sort !== 'name') h.set('sort', state.sort);
  history.replaceState(null, '', '#' + h);
}

function buildToolbar() {
  document.querySelectorAll('#tabs button').forEach((b) => b.classList.toggle('on', b.dataset.tab === state.tab));
  const levels = [...new Set(DATA[state.tab].map((i) => i.level).filter(Boolean))].sort((a, b) => levelKey(a) - levelKey(b) || a.localeCompare(b));
  // Keep the level the user picked across tabs; show all levels only where it doesn't exist.
  state.level = levels.includes(state.pickedLevel) ? state.pickedLevel : '';
  $('#level').innerHTML = `<option value="">All levels</option>` + levels.map((l) => `<option value="${esc(l)}">${esc(levelLabel(l))}</option>`).join('');
  $('#level').value = state.level;
  const chips = TABS[state.tab].chips;
  if (!chips.some(([k]) => k === state.chip)) state.chip = 'all';
  $('#chips').innerHTML = chips.map(([k, l]) => `<button class="chip ${k === state.chip ? 'on' : ''}" data-chip="${k}">${l}</button>`).join('');
  $('#search').value = state.q;
  $('#sort').value = state.sort;
  $('#renderAll').hidden = !(state.tab === 'static' || state.tab === 'animated');
}

function refresh() {
  writeHash();
  buildToolbar();
  state.list = filtered();
  state.shown = 0;
  thumbs.reset();
  stopAudio();
  const grid = $('#grid');
  grid.innerHTML = '';
  grid.className = state.tab === 'sounds' ? 'sounds' : '';
  const total = DATA[state.tab].length;
  $('#summary').textContent = state.list.length === total
    ? `${fmtNum(total)} ${TABS[state.tab].label}`
    : `${fmtNum(state.list.length)} of ${fmtNum(total)} ${TABS[state.tab].label}`;
  $('#empty').hidden = state.list.length > 0;
  showMore();
}

function showMore() {
  const grid = $('#grid');
  const end = Math.min(state.list.length, state.shown + PAGE);
  const frag = document.createDocumentFragment();
  for (let i = state.shown; i < end; i++) frag.appendChild(makeCard(state.list[i], i));
  grid.appendChild(frag);
  state.shown = end;
}
new IntersectionObserver((es) => { if (es[0].isIntersecting && DATA && state.shown < state.list.length) showMore(); }, { rootMargin: '800px' }).observe($('#more'));

// ---------------------------------------------------------------- cards
function makeCard(it, i) {
  const el = document.createElement('div');
  el.className = 'card'; el.tabIndex = 0; el.dataset.i = i;
  if (state.tab === 'sounds') return soundCard(el, it, i);
  let img = '', badge = '', sub = '';
  if (state.tab === 'textures') {
    img = `<img loading="lazy" decoding="async" src="${fileUrl(it.path)}" alt="">`;
    badge = it.dims ? `${it.dims[0]}×${it.dims[1]}` : '';
    sub = levelLabel(it.level);
  } else {
    img = it.has_thumb ? `<img loading="lazy" src="/api/thumb/${it.thumb}.png" alt="">` : `<span class="ph">…</span>`;
    badge = state.tab === 'animated' ? `${it.clips.length} clip${it.clips.length === 1 ? '' : 's'}` : (it.folder === 'levels' ? 'level' : '');
    sub = [levelLabel(it.level) || it.folder, fmtNum(it.tris) + ' tris'].filter(Boolean).join(' · ');
    if (it.folder === 'levels') sub = [it.level, fmtNum(it.tris) + ' tris'].filter(Boolean).join(' · ');
  }
  el.innerHTML = `<div class="thumb ${state.tab === 'textures' ? 'tex' : ''}">${img}${badge ? `<span class="badge">${esc(badge)}</span>` : ''}</div>
    <div class="meta"><div class="name" title="${esc(it.path)}">${esc(displayName(it))}</div><div class="sub">${esc(sub)}</div></div>`;
  if (state.tab !== 'textures' && !it.has_thumb) thumbs.watch(el, it);
  el.addEventListener('click', () => openDetail(i));
  el.addEventListener('keydown', (e) => { if (e.key === 'Enter') openDetail(i); });
  return el;
}

// ---------------------------------------------------------------- sounds
const audio = new Audio();
audio.preload = 'auto';
let playing = null; // { el, it }
function soundCard(el, it, i) {
  el.className = 'card snd';
  const ch = it.channels === 2 ? 'stereo' : it.channels === 1 ? 'mono' : '';
  el.innerHTML = `<button class="play" title="Play / pause">▶</button>
    <div class="body"><div class="nameRow"><div class="name" title="${esc(it.path)}">${esc(it.name)}</div>
    <button class="sreveal" title="${REVEAL_LABEL}">${REVEAL_LABEL}</button></div>
    <div class="wave"><canvas></canvas><div class="prog"></div></div>
    <div class="sub">${esc([fmtTime(it.duration), levelLabel(it.level), it.group === 'sfx' ? 'effect' : 'music/speech', ch].filter(Boolean).join(' · '))}</div></div>`;
  el.querySelector('.play').addEventListener('click', () => toggleSound(el, it));
  el.querySelector('.sreveal').addEventListener('click', async (e) => {
    const err = await revealFile(it.path);
    e.target.textContent = err || REVEAL_LABEL;
    if (err) setTimeout(() => { e.target.textContent = REVEAL_LABEL; }, 3000);
  });
  el.querySelector('.wave').addEventListener('click', (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    const f = (e.clientX - r.left) / r.width;
    if (playing?.el !== el) toggleSound(el, it, f); else audio.currentTime = f * (audio.duration || it.duration || 0);
  });
  el.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleSound(el, it); } });
  waves.observe(el); el._it = it;
  return el;
}
function toggleSound(el, it, startFrac) {
  if (playing?.el === el && startFrac === undefined) { audio.paused ? audio.play() : audio.pause(); return; }
  stopAudio();
  playing = { el, it };
  el.classList.add('playing');
  audio.src = fileUrl(it.path);
  audio.onloadedmetadata = () => { if (startFrac) audio.currentTime = startFrac * audio.duration; };
  audio.play().catch(() => {});
}
function stopAudio() {
  if (!playing) return;
  audio.pause();
  playing.el.classList.remove('playing');
  playing.el.querySelector('.play').textContent = '▶';
  playing.el.querySelector('.prog').style.width = '0';
  playing = null;
}
audio.addEventListener('play', () => { if (playing) playing.el.querySelector('.play').textContent = '❚❚'; });
audio.addEventListener('pause', () => { if (playing) playing.el.querySelector('.play').textContent = '▶'; });
audio.addEventListener('ended', () => { if (playing) playing.el.querySelector('.prog').style.width = '0'; });
(function tick() {
  if (playing && audio.duration) playing.el.querySelector('.prog').style.width = (100 * audio.currentTime / audio.duration) + '%';
  requestAnimationFrame(tick);
})();

const waves = new IntersectionObserver((es) => {
  for (const e of es) {
    if (!e.isIntersecting) continue;
    waves.unobserve(e.target);
    const it = e.target._it;
    fetch('/api/peaks?path=' + encodeURIComponent(it.path)).then((r) => r.json()).then((p) => drawWave(e.target.querySelector('canvas'), p)).catch(() => {});
  }
}, { rootMargin: '300px' });
function drawWave(cv, peaks) {
  const w = cv.clientWidth || 200, h = cv.clientHeight || 40, dpr = devicePixelRatio || 1;
  cv.width = w * dpr; cv.height = h * dpr;
  const g = cv.getContext('2d'); g.scale(dpr, dpr);
  g.fillStyle = '#5f6b80';
  const bw = w / Math.max(1, peaks.length);
  peaks.forEach(([lo, hi], i) => {
    const y0 = h / 2 - (hi / 128) * (h / 2), y1 = h / 2 - (lo / 128) * (h / 2);
    g.fillRect(i * bw, y0, Math.max(1, bw - 0.5), Math.max(1, y1 - y0));
  });
}

// ---------------------------------------------------------------- 3D helpers
const loader = new GLTFLoader();
function addLights(scene) {
  scene.add(new THREE.HemisphereLight(0xffffff, 0x445066, 2.2));
  const d = new THREE.DirectionalLight(0xffffff, 2.0); d.position.set(3, 5, 4); scene.add(d);
}
// Transparency and blend modes. The glTF alphaMode (OPAQUE / MASK / BLEND) is standard and the
// loader applies it. The converter adds the game's own blend state in material.extras.btg
// ({blend: "opaque"|"alpha"|"additive"|"cutout", depthWrite, srcBlend, dstBlend} with D3DBLEND
// factor numbers), which three.js puts in userData. Texture alpha on OPAQUE materials is a gloss
// mask, not transparency, so it is ignored unless the viewer is asked to treat it as a cutout.
const BLENDS = {
  additive: { blending: THREE.AdditiveBlending },
  subtractive: { blending: THREE.CustomBlending, blendEquation: THREE.ReverseSubtractEquation, blendSrc: THREE.SrcAlphaFactor, blendDst: THREE.OneFactor },
  multiply: { blending: THREE.CustomBlending, blendEquation: THREE.AddEquation, blendSrc: THREE.DstColorFactor, blendDst: THREE.ZeroFactor },
  alpha: { blending: THREE.NormalBlending },
};
// D3DBLEND -> three.js blend factor
const D3D = { 1: THREE.ZeroFactor, 2: THREE.OneFactor, 3: THREE.SrcColorFactor, 4: THREE.OneMinusSrcColorFactor,
  5: THREE.SrcAlphaFactor, 6: THREE.OneMinusSrcAlphaFactor, 7: THREE.DstAlphaFactor, 8: THREE.OneMinusDstAlphaFactor,
  9: THREE.DstColorFactor, 10: THREE.OneMinusDstColorFactor, 11: THREE.SrcAlphaSaturateFactor };
function btgOf(m) { return m.userData.btg || {}; }
function blendState(m, kind) {
  const b = btgOf(m);
  if (D3D[b.srcBlend] !== undefined && D3D[b.dstBlend] !== undefined)
    return { blending: THREE.CustomBlending, blendEquation: THREE.AddEquation, blendSrc: D3D[b.srcBlend], blendDst: D3D[b.dstBlend] };
  return BLENDS[kind];
}
function blendKind(m) {
  const b = String(btgOf(m).blend || m.userData.btg_blend || '').toLowerCase();
  if (b === 'cutout') return 'cutout';
  if (BLENDS[b]) return b;
  if (b === 'opaque') return 'opaque';
  if (m.transparent) return 'alpha';
  if (m.alphaTest > 0) return 'cutout';
  return 'opaque';
}
// mode: 'file' (as the glTF says), 'off' (everything opaque) or 'cutout' (use texture alpha as a cutout everywhere)
function applyTransparency(root, mode = 'file') {
  root.traverse((o) => {
    if (!o.isMesh) return;
    for (const m of [].concat(o.material)) {
      if (!m.userData._orig) m.userData._orig = { transparent: m.transparent, alphaTest: m.alphaTest, depthWrite: m.depthWrite, kind: blendKind(m) };
      const orig = m.userData._orig;
      Object.assign(m, { transparent: false, alphaTest: 0, depthWrite: true, blending: THREE.NormalBlending, blendEquation: THREE.AddEquation, blendSrc: THREE.SrcAlphaFactor, blendDst: THREE.OneMinusSrcAlphaFactor });
      if (mode === 'cutout') {
        if (m.map) m.alphaTest = 0.5;
        if (BLENDS[orig.kind] && orig.kind !== 'alpha') Object.assign(m, blendState(m, orig.kind), { transparent: true, depthWrite: false });
      } else if (mode === 'file') {
        if (orig.kind === 'cutout') m.alphaTest = orig.alphaTest || 0.5;
        else if (BLENDS[orig.kind]) Object.assign(m, blendState(m, orig.kind), { transparent: true, depthWrite: false });
        const dw = typeof btgOf(m).depthWrite === 'boolean' ? btgOf(m).depthWrite : m.userData.btg_depth_write;
        if (typeof dw === 'boolean' && orig.kind !== 'opaque') m.depthWrite = dw;
      }
      m.needsUpdate = true;
    }
  });
}
function materialSummary(root) {
  const seen = new Set(), n = {};
  root.traverse((o) => { if (o.isMesh) for (const m of [].concat(o.material)) if (!seen.has(m)) { seen.add(m); const k = m.userData._orig?.kind || blendKind(m); n[k] = (n[k] || 0) + 1; } });
  const order = ['opaque', 'cutout', 'alpha', 'additive', 'subtractive', 'multiply'];
  return `${seen.size}` + (Object.keys(n).some((k) => k !== 'opaque') ? ' (' + order.filter((k) => n[k]).map((k) => `${n[k]} ${k}`).join(', ') + ')' : '');
}
function prepare(root, transparency) {
  root.traverse((o) => {
    if (o.isMesh) {
      o.frustumCulled = false;
      for (const m of [].concat(o.material)) { m.side = THREE.DoubleSide; }
    }
  });
  applyTransparency(root, transparency);
}
function frame(camera, object, controls, dir = new THREE.Vector3(1, 0.55, 1.25)) {
  object.updateMatrixWorld(true);
  object.traverse((o) => { if (o.isSkinnedMesh) o.computeBoundingBox(); }); // three caches these; refresh for the current pose
  const box = new THREE.Box3().setFromObject(object);
  if (box.isEmpty()) box.set(new THREE.Vector3(-1, -1, -1), new THREE.Vector3(1, 1, 1));
  const sphere = box.getBoundingSphere(new THREE.Sphere());
  const r = Math.max(sphere.radius, 1e-3);
  const dist = r / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2)) * 1.05;
  camera.position.copy(sphere.center).addScaledVector(dir.normalize(), dist);
  camera.near = dist / 1000; camera.far = dist * 20; camera.updateProjectionMatrix();
  camera.lookAt(sphere.center);
  if (controls) { controls.target.copy(sphere.center); controls.update(); }
  return { box, sphere };
}
// ---------------------------------------------------------------- animated texture layers
// The game has no flipbooks: a material is 1-4 texture layers whose UVs scroll (UV units/s) and
// rotate (rad/s) around the texture centre, combined like D3D texture stages. The converter lists
// them in material.extras.btg.layers = [{image, op, scroll: [u, v], rotate}, ...]; layer 0 is the
// glTF base colour texture. Ops: base, add, modulate, subtract, blendtexturealpha.
const texTime = { value: 0 };
const LAYER_OPS = {
  add: 'c.rgb += t.rgb;',
  modulate: 'c.rgb *= t.rgb;',
  subtract: 'c.rgb = max(c.rgb - t.rgb, 0.0);', // which operand comes first is inferred, not confirmed
  blendtexturealpha: 'c.rgb = mix(c.rgb, t.rgb, t.a);',
};
const texLoader = new THREE.TextureLoader();
// Texture address mode per layer, as [wrapS, wrapT]. Uses the game's own D3DTEXTUREADDRESS values when
// the converter exports them (layer.address = [u, v]: 1 wrap, 2 mirror, 3 clamp, 4 border). Without
// them, a layer that rotates in place is treated as a non-tiling decal and clamped, so the neighbouring
// tiles don't show up in its corners at 45 degrees; everything else tiles.
const D3D_ADDRESS = { 1: THREE.RepeatWrapping, 2: THREE.MirroredRepeatWrapping, 3: THREE.ClampToEdgeWrapping, 4: THREE.ClampToEdgeWrapping };
function layerWrap(l) {
  const a = l.address;
  if (Array.isArray(a) && D3D_ADDRESS[a[0]] !== undefined) return [D3D_ADDRESS[a[0]], D3D_ADDRESS[a[1]] ?? D3D_ADDRESS[a[0]]];
  const scrolls = (l.scroll || []).some((x) => x);
  return l.rotate && !scrolls ? [THREE.ClampToEdgeWrapping, THREE.ClampToEdgeWrapping] : [THREE.RepeatWrapping, THREE.RepeatWrapping];
}
function setupLayers(root, baseUrl) {
  let animated = 0;
  root.traverse((o) => {
    if (!o.isMesh) return;
    for (const m of [].concat(o.material)) {
      const layers = (m.userData.btg || {}).layers;
      if (!m.map || !Array.isArray(layers) || !layers.length || m.userData._layers) continue;
      const moving = layers.some((l) => (l.scroll || []).some((x) => x) || l.rotate);
      if (layers.length < 2 && !moving) continue;
      animated++;
      m.userData._layers = true;
      // The loader shares one Texture between materials; give this one its own wrap settings.
      m.map = m.map.clone(); [m.map.wrapS, m.map.wrapT] = layerWrap(layers[0]); m.map.needsUpdate = true;
      const n = Math.min(layers.length, 4);
      const extra = [];
      for (let k = 1; k < n; k++) {
        const t = texLoader.load(new URL(layers[k].image, baseUrl).href);
        t.flipY = false; t.colorSpace = THREE.SRGBColorSpace; [t.wrapS, t.wrapT] = layerWrap(layers[k]);
        extra.push(t);
      }
      m.userData._btgTex = extra;
      const scroll = [0, 1, 2, 3].map((k) => new THREE.Vector2(...((layers[k] || {}).scroll || [0, 0])));
      const rot = [0, 1, 2, 3].map((k) => +((layers[k] || {}).rotate || 0));
      const ops = layers.slice(1, n).map((l) => LAYER_OPS[String(l.op).toLowerCase()] || LAYER_OPS.modulate);
      m.onBeforeCompile = (sh) => {
        sh.uniforms.btgTime = texTime;
        sh.uniforms.btgScroll = { value: scroll };
        sh.uniforms.btgRot = { value: rot };
        extra.forEach((t, k) => { sh.uniforms['btgMap' + (k + 1)] = { value: t }; });
        sh.vertexShader = sh.vertexShader
          .replace('#include <common>', '#include <common>\nvarying vec2 vBtgUv;')
          .replace('#include <uv_vertex>', '#include <uv_vertex>\nvBtgUv = uv;');
        sh.fragmentShader = sh.fragmentShader
          .replace('#include <common>', `#include <common>
varying vec2 vBtgUv;
uniform float btgTime; uniform vec2 btgScroll[4]; uniform float btgRot[4];
${extra.map((_, k) => `uniform sampler2D btgMap${k + 1};`).join('\n')}
vec2 btgUv(int k) {
  float a = btgRot[k] * btgTime;
  vec2 p = mat2(cos(a), sin(a), -sin(a), cos(a)) * (vBtgUv - 0.5);
  return p + 0.5 + btgScroll[k] * btgTime;
}`)
          .replace('#include <map_fragment>', `{
  vec4 c = texture2D(map, btgUv(0)), t;
${ops.map((op, k) => `  t = texture2D(btgMap${k + 1}, btgUv(${k + 1})); ${op}`).join('\n')}
  diffuseColor *= c;
}`);
      };
      m.customProgramCacheKey = () => 'btg' + n + ops.join('');
      m.needsUpdate = true;
    }
  });
  return animated;
}

function disposeTree(root) {
  root.traverse((o) => {
    if (o.geometry) o.geometry.dispose();
    for (const m of [].concat(o.material || [])) {
      for (const t of m.userData._btgTex || []) t.dispose();
      for (const v of Object.values(m)) if (v && v.isTexture) { v.dispose(); v.image?.close?.(); }
      m.dispose();
    }
  });
}

// ---------------------------------------------------------------- thumbnail renderer
const thumbs = (() => {
  const SIZE = 256;
  let renderer = null, scene, camera;
  const visible = new Set(), all = [];
  let busy = false, gen = 0, renderAllOn = false, done = 0;
  const io = new IntersectionObserver((es) => {
    for (const e of es) e.isIntersecting ? visible.add(e.target) : visible.delete(e.target);
    pump();
  }, { rootMargin: '200px' });

  function init() {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
    renderer.setSize(SIZE, SIZE, false);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    scene = new THREE.Scene(); addLights(scene);
    camera = new THREE.PerspectiveCamera(35, 1, 0.01, 1000);
  }
  function next() {
    for (const el of visible) if (!el._done) return el;
    if (renderAllOn) {
      while (all.length) { const el = all.shift(); if (!el._done) return el; }
      renderAllOn = false; status('All thumbnails rendered');
    }
    return null;
  }
  async function pump() {
    if (busy) return;
    const el = next(); if (!el) return;
    busy = true; const myGen = gen;
    el._done = true;
    try { await render(el._it, el); } catch (err) { console.warn('thumbnail failed', el._it.path, err); el.querySelector('.ph') && (el.querySelector('.ph').textContent = 'no preview'); }
    busy = false;
    if (renderAllOn && myGen === gen) status(`Rendering thumbnails… ${++done} done, ${all.length} left`);
    setTimeout(pump, 0);
  }
  async function render(it, el) {
    if (!renderer) init();
    const ph = el.querySelector('.ph'); if (ph) ph.textContent = 'rendering…';
    const gltf = await loader.loadAsync(fileUrl(it.path));
    const root = gltf.scene; prepare(root); scene.add(root);
    if (gltf.animations.length) {
      const mixer = new THREE.AnimationMixer(root);
      mixer.clipAction(gltf.animations[0]).play(); mixer.update(0);
    }
    frame(camera, root, null, it.folder === 'levels' ? new THREE.Vector3(0.6, 0.9, 0.8) : undefined);
    renderer.render(scene, camera);
    const blob = await new Promise((res) => renderer.domElement.toBlob(res, 'image/png'));
    scene.remove(root); disposeTree(root);
    await fetch('/api/thumb/' + it.thumb, { method: 'POST', body: blob, headers: { 'Content-Type': 'image/png' } }).then((r) => { if (r.ok) it.has_thumb = true; }).catch(() => {});
    const img = new Image(); img.src = URL.createObjectURL(blob); img.alt = '';
    (el.querySelector('.ph') || el.querySelector('.thumb img'))?.replaceWith(img);
  }
  function status(s) { $('#status').textContent = s; }
  return {
    watch(el, it) { el._it = it; io.observe(el); },
    reset() { io.disconnect(); visible.clear(); all.length = 0; renderAllOn = false; gen++; status(''); },
    renderAll() {
      const pending = state.list.filter((it) => !it.has_thumb);
      if (!pending.length) { status('All thumbnails are ready'); return; }
      // Cards not on the page yet get a detached element; the grid picks the cached thumbnail up later.
      const onPage = new Map([...document.querySelectorAll('#grid .card')].map((c) => [state.list[+c.dataset.i], c]));
      for (const it of pending) {
        let el = onPage.get(it);
        if (!el) { el = document.createElement('div'); el.innerHTML = '<div class="thumb"><span class="ph"></span></div>'; el._it = it; }
        all.push(el);
      }
      renderAllOn = true; done = 0; status(`Rendering thumbnails… ${all.length} left`); pump();
    },
  };
})();

// ---------------------------------------------------------------- detail view
const view = (() => {
  const canvas = $('#view3d');
  let renderer = null, scene, camera, controls, clock = new THREE.Clock();
  let current = null, mixer = null, action = null, clips = [], grid = null, skel = null, followBone = null, lastFollow = new THREE.Vector3();
  const opts = { wire: false, grid: true, skel: false, follow: true, speed: 1, playing: true, transparency: 'file', cam: 'orbit', texanim: true };
  try { if (localStorage.getItem('btgCam') === 'fly') opts.cam = 'fly'; } catch {}
  // Fly camera: WASD to move, Q/E down/up, Shift faster, drag to look, wheel to change speed.
  const fly = { yaw: 0, pitch: 0, keys: new Set(), mult: 1, base: 1, drag: null };
  const FLY_KEYS = new Set(['KeyW', 'KeyA', 'KeyS', 'KeyD', 'KeyQ', 'KeyE', 'ShiftLeft', 'ShiftRight']);
  let token = 0, texLayers = 0, viewDir = new THREE.Vector3(1, 0.55, 1.25);

  function init() {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.setPixelRatio(devicePixelRatio);
    scene = new THREE.Scene(); scene.background = new THREE.Color(0x0e1014); addLights(scene);
    camera = new THREE.PerspectiveCamera(40, 1, 0.01, 1000);
    controls = new OrbitControls(camera, canvas); controls.enableDamping = true;
    new ResizeObserver(resize).observe(canvas);
    camera.rotation.order = 'YXZ';
    canvas.addEventListener('contextmenu', (e) => { if (opts.cam === 'fly') e.preventDefault(); });
    canvas.addEventListener('pointerdown', (e) => {
      if (opts.cam !== 'fly') return;
      fly.drag = { x: e.clientX, y: e.clientY }; canvas.setPointerCapture(e.pointerId);
    });
    canvas.addEventListener('pointermove', (e) => {
      if (opts.cam !== 'fly' || !fly.drag) return;
      fly.yaw -= (e.clientX - fly.drag.x) * 0.004; fly.pitch -= (e.clientY - fly.drag.y) * 0.004;
      fly.pitch = Math.max(-1.55, Math.min(1.55, fly.pitch));
      fly.drag = { x: e.clientX, y: e.clientY };
    });
    canvas.addEventListener('pointerup', () => { fly.drag = null; });
    canvas.addEventListener('wheel', (e) => {
      if (opts.cam !== 'fly') return;
      e.preventDefault();
      fly.mult = Math.max(0.05, Math.min(50, fly.mult * (e.deltaY < 0 ? 1.25 : 0.8)));
      const l = $('#flySpeed'); if (l) l.textContent = '×' + fly.mult.toFixed(2);
    }, { passive: false });
    addEventListener('keydown', (e) => {
      if (opts.cam !== 'fly' || $('#overlay').hidden || canvas.hidden || !FLY_KEYS.has(e.code)) return;
      if (['INPUT', 'SELECT', 'TEXTAREA'].includes(e.target.tagName) && e.target.type !== 'range') return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      fly.keys.add(e.code); e.preventDefault();
    });
    addEventListener('keyup', (e) => fly.keys.delete(e.code));
    addEventListener('blur', () => fly.keys.clear());
    renderer.setAnimationLoop(loop);
  }
  function resize() {
    const w = canvas.clientWidth, h = canvas.clientHeight; if (!w || !h) return;
    renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
  }
  function loop() {
    if ($('#overlay').hidden || canvas.hidden) return;
    const dt = clock.getDelta();
    if (mixer && opts.playing) mixer.update(dt * opts.speed);
    if (opts.texanim) texTime.value += dt;
    if (followBone && opts.follow) {
      const p = followBone.getWorldPosition(new THREE.Vector3());
      const d = p.clone().sub(lastFollow); lastFollow.copy(p);
      camera.position.add(d); controls.target.add(d);
    }
    if (opts.cam === 'fly') {
      const k = fly.keys, v = new THREE.Vector3();
      const fwd = new THREE.Vector3(-Math.sin(fly.yaw) * Math.cos(fly.pitch), Math.sin(fly.pitch), -Math.cos(fly.yaw) * Math.cos(fly.pitch));
      const right = new THREE.Vector3(Math.cos(fly.yaw), 0, -Math.sin(fly.yaw));
      if (k.has('KeyW')) v.add(fwd); if (k.has('KeyS')) v.sub(fwd);
      if (k.has('KeyD')) v.add(right); if (k.has('KeyA')) v.sub(right);
      if (k.has('KeyE')) v.y += 1; if (k.has('KeyQ')) v.y -= 1;
      if (v.lengthSq()) {
        const fast = k.has('ShiftLeft') || k.has('ShiftRight') ? 4 : 1;
        camera.position.addScaledVector(v.normalize(), fly.base * fly.mult * fast * Math.min(dt, 0.1));
      }
      camera.rotation.set(fly.pitch, fly.yaw, 0);
    }
    if (action) {
      const t = action.time, dur = action.getClip().duration || 0;
      const tl = $('#timeline'); if (tl && !tl._drag) tl.value = dur ? t / dur : 0;
      const lab = $('#timeLabel'); if (lab) lab.textContent = `${fmtTime(t)} / ${fmtTime(dur)}`;
    }
    if (opts.cam === 'orbit') controls.update();
    renderer.render(scene, camera);
  }
  // Point the fly camera the way the orbit camera was looking, and back.
  function setCam(mode) {
    opts.cam = mode;
    try { localStorage.setItem('btgCam', mode); } catch {}
    if (mode === 'fly') {
      const d = controls.target.clone().sub(camera.position).normalize();
      fly.yaw = Math.atan2(-d.x, -d.z); fly.pitch = Math.asin(Math.max(-1, Math.min(1, d.y)));
      controls.enabled = false;
    } else {
      const dir = camera.getWorldDirection(new THREE.Vector3());
      controls.target.copy(camera.position).addScaledVector(dir, fly.base * 2);
      controls.enabled = true; controls.update();
    }
    fly.keys.clear();
  }
  function clear() {
    if (current) { scene.remove(current); disposeTree(current); current = null; }
    if (skel) { scene.remove(skel); skel.dispose(); skel = null; }
    if (grid) { scene.remove(grid); grid.dispose(); grid = null; }
    mixer = null; action = null; clips = []; followBone = null; texLayers = 0;
  }
  async function show(it) {
    if (!renderer) init();
    const my = ++token;
    clear(); resize();
    $('#loading').hidden = false; $('#loading').textContent = 'Loading…';
    let gltf;
    try { gltf = await loader.loadAsync(fileUrl(it.path)); }
    catch (e) { if (my === token) $('#loading').textContent = 'Could not load this model: ' + e.message; return; }
    if (my !== token) { disposeTree(gltf.scene); return; }
    $('#loading').hidden = true;
    current = gltf.scene; prepare(current, opts.transparency); scene.add(current);
    texLayers = setupLayers(current, new URL(fileUrl(it.path), location.href));
    const mats = $('#dMaterials'); if (mats) mats.textContent = materialSummary(current);
    clips = gltf.animations;
    if (clips.length) { mixer = new THREE.AnimationMixer(current); playClip(0, false); }
    viewDir = it.folder === 'levels' ? new THREE.Vector3(0.6, 0.9, 0.8) : new THREE.Vector3(1, 0.55, 1.25);
    const { box, sphere } = frame(camera, current, controls, viewDir.clone());
    fly.base = Math.max(sphere.radius * 0.6, 0.05);
    if (opts.cam === 'fly') setCam('fly');
    const size = Math.max(box.max.x - box.min.x, box.max.z - box.min.z) * 1.6 || 2;
    grid = new THREE.GridHelper(size, 20, 0x3a4150, 0x262b35); grid.position.set(sphere.center.x, box.min.y, sphere.center.z); grid.visible = opts.grid; scene.add(grid);
    if (!followBone) current.traverse((o) => { if (!followBone && o.isBone) followBone = o; });
    if (followBone) { skel = new THREE.SkeletonHelper(current); skel.visible = opts.skel; scene.add(skel); lastFollow.copy(followBone.getWorldPosition(new THREE.Vector3())); }
    applyWire();
    buildControls(it);
  }
  function playClip(i, reframe = true) {
    mixer.stopAllAction();
    action = mixer.clipAction(clips[i]); action.reset().play();
    mixer.update(0);
    // Follow the bone that carries the clip's root motion (cutscene clips walk characters across the level).
    const moved = clips[i].tracks.find((t) => t.name.endsWith('.position') && current.getObjectByName(t.name.slice(0, -9))?.isBone);
    if (moved) followBone = current.getObjectByName(moved.name.slice(0, -9));
    if (reframe) reset();
    if (followBone) lastFollow.copy(followBone.getWorldPosition(new THREE.Vector3()));
  }
  // Frame the model as it is posed right now, keeping the current viewing direction.
  function reset() {
    if (!current) return;
    if (opts.cam === 'fly') controls.target.copy(camera.position).addScaledVector(camera.getWorldDirection(new THREE.Vector3()), 1);
    const dir2 = camera.position.clone().sub(controls.target);
    const { box, sphere } = frame(camera, current, controls, dir2.lengthSq() ? dir2 : viewDir.clone());
    if (opts.cam === 'fly') setCam('fly');
    if (grid) grid.position.set(sphere.center.x, box.min.y, sphere.center.z);
    if (followBone) lastFollow.copy(followBone.getWorldPosition(new THREE.Vector3()));
  }
  function applyWire() { current?.traverse((o) => { if (o.isMesh) for (const m of [].concat(o.material)) m.wireframe = opts.wire; }); }

  function buildControls(it) {
    const c = $('#dControls');
    const tg = (k, label) => `<button class="toggle ${opts[k] ? 'on' : ''}" data-k="${k}">${label}</button>`;
    let html = `<div class="row">${tg('wire', 'Wireframe')}${tg('grid', 'Grid')}${texLayers ? tg('texanim', 'Animate textures') : ''}${skel ? tg('skel', 'Skeleton') : ''}${clips.length ? tg('follow', 'Follow') : ''}<button class="toggle" id="resetView">Reset view</button></div>
      <div><label>Camera</label><div class="row">
        <button class="toggle ${opts.cam === 'orbit' ? 'on' : ''}" data-cam="orbit">Orbit</button>
        <button class="toggle ${opts.cam === 'fly' ? 'on' : ''}" data-cam="fly">Fly (WASD)</button>
        <span id="flyInfo" class="hint" ${opts.cam === 'fly' ? '' : 'hidden'}>Speed <b id="flySpeed">×${fly.mult.toFixed(2)}</b></span></div>
        <p class="hint" id="flyHelp" ${opts.cam === 'fly' ? '' : 'hidden'}>W A S D move · Q / E down / up · hold Shift to go faster · drag to look around · mouse wheel changes speed</p>
      </div>
      <div><label>Transparency</label><select id="transSel">
        <option value="file">As stored in the file</option><option value="cutout">Texture alpha as cutout</option><option value="off">Off (all opaque)</option>
      </select></div>`;
    if (clips.length) {
      html += `<div><label>Animation (${clips.length})</label><select id="clipSel">${clips.map((a, i) => `<option value="${i}">${esc(a.name || 'clip ' + i)} (${a.duration.toFixed(1)}s)</option>`).join('')}</select></div>
      <div class="row"><button class="toggle" id="playBtn">${opts.playing ? 'Pause' : 'Play'}</button>
        <select id="speedSel">${[0.1, 0.25, 0.5, 1, 1.5, 2].map((s) => `<option value="${s}" ${s === opts.speed ? 'selected' : ''}>${s}×</option>`).join('')}</select>
        <span id="timeLabel"></span></div>
      <input id="timeline" type="range" min="0" max="1" step="0.001" value="0">`;
    }
    c.innerHTML = html;
    c.querySelectorAll('[data-k]').forEach((b) => b.onclick = () => {
      const k = b.dataset.k; opts[k] = !opts[k]; b.classList.toggle('on', opts[k]);
      if (k === 'wire') applyWire(); if (k === 'grid' && grid) grid.visible = opts.grid; if (k === 'skel' && skel) skel.visible = opts.skel;
      if (k === 'follow' && followBone) lastFollow.copy(followBone.getWorldPosition(new THREE.Vector3()));
    });
    $('#resetView').onclick = reset;
    c.querySelectorAll('[data-cam]').forEach((b) => b.onclick = () => {
      setCam(b.dataset.cam);
      c.querySelectorAll('[data-cam]').forEach((x) => x.classList.toggle('on', x.dataset.cam === opts.cam));
      $('#flyInfo').hidden = $('#flyHelp').hidden = opts.cam !== 'fly';
      b.blur(); // keep keyboard focus off the button so WASD and Space go to the view
    });
    $('#transSel').value = opts.transparency;
    $('#transSel').onchange = (e) => { opts.transparency = e.target.value; applyTransparency(current, opts.transparency); };
    if (clips.length) {
      $('#clipSel').onchange = (e) => playClip(+e.target.value);
      $('#playBtn').onclick = (e) => { opts.playing = !opts.playing; e.target.textContent = opts.playing ? 'Pause' : 'Play'; };
      $('#speedSel').onchange = (e) => opts.speed = +e.target.value;
      const tl = $('#timeline');
      tl.onpointerdown = () => tl._drag = true; tl.onpointerup = () => tl._drag = false;
      tl.oninput = () => { if (!action) return; action.time = +tl.value * action.getClip().duration; mixer.update(0); };
    }
  }
  return { show, clear, togglePlay() { const b = $('#playBtn'); if (b) b.click(); } };
})();

let detailIndex = -1;
const imgView = { bg: 'checker', alpha: true, zoom: 0 };
const REVEAL_LABEL = /Mac/i.test(navigator.platform) ? 'Show in Finder' : /Win/i.test(navigator.platform) ? 'Show in File Explorer' : 'Show in file manager';
function fillLinks(el, path) {
  el.innerHTML = `<button class="reveal">${REVEAL_LABEL}</button><a href="${fileUrl(path)}" download>Download</a><span class="revealMsg"></span>`;
  el.querySelector('.reveal').onclick = async () => {
    const msg = el.querySelector('.revealMsg'); msg.textContent = '';
    msg.textContent = await revealFile(path);
  };
}
// Asks the local server to open File Explorer / Finder at the file. Returns an error message, or ''.
async function revealFile(path) {
  try {
    const r = await fetch('/api/reveal', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path }) });
    return r.ok ? '' : 'Could not open the folder' + (r.status === 404 ? ': file not found' : '');
  } catch { return 'Could not reach the viewer'; }
}
function showPane(id) {
  for (const p of ['paneDetails', 'paneTex', 'paneTexView']) $('#' + p).hidden = p !== id;
  $('#dTabs').querySelectorAll('button').forEach((b) => b.classList.toggle('on', b.dataset.pane === id));
}
function backToModel() {
  $('#viewImage').hidden = true; $('#view3d').hidden = false; $('#dTabs').hidden = false;
  showPane('paneTex');
}
function openModelTexture(path) {
  $('#view3d').hidden = true; $('#viewImage').hidden = false; $('#dTabs').hidden = true;
  showPane('paneTexView');
  $('#tTitle').textContent = path.split('/').pop();
  const tex = { path };
  showImage(tex, $('#tControls'), () => {
    const img = $('#bigImg');
    $('#tInfo').innerHTML = `<dt>Dimensions</dt><dd>${img.naturalWidth} × ${img.naturalHeight}</dd><dt>File</dt><dd>${esc(path)}</dd>`;
  });
  fillLinks($('#tLinks'), path);
}
function fillModelTextures(it) {
  const imgs = it.images || [];
  $('#texCount').textContent = imgs.length;
  $('#texGrid').innerHTML = imgs.length ? imgs.map((p, k) => `<button class="ttile" data-k="${k}" title="${esc(p)}"><div class="thumb"><img loading="lazy" src="${fileUrl(p)}" alt=""></div><span>…</span></button>`).join('')
    : '<p class="sub">This model has no textures.</p>';
  $('#texGrid').querySelectorAll('.ttile').forEach((b) => {
    const img = b.querySelector('img');
    img.onload = () => { b.querySelector('span').textContent = `${img.naturalWidth}×${img.naturalHeight}`; };
    b.onclick = () => openModelTexture(imgs[+b.dataset.k]);
  });
}
function openDetail(i) {
  detailIndex = i;
  const it = state.list[i]; if (!it) return;
  $('#overlay').hidden = false;
  $('#dTitle').textContent = displayName(it);
  const isModel = state.tab === 'static' || state.tab === 'animated';
  $('#view3d').hidden = !isModel; $('#viewImage').hidden = isModel;
  $('#dTabs').hidden = !isModel; showPane('paneDetails');
  if (isModel) fillModelTextures(it);
  const info = [];
  const add = (k, v) => { if (v !== undefined && v !== '' && v !== null) info.push(`<dt>${k}</dt><dd>${esc(v)}</dd>`); };
  if (isModel) {
    add('Level', levelLabel(it.level)); add('Group', it.folder); add('Triangles', fmtNum(it.tris)); add('Vertices', fmtNum(it.verts));
    if (it.bones) add('Bones', it.bones); if (it.clips.length) add('Clips', it.clips.length);
    add('Textures', it.textures); info.push('<dt>Materials</dt><dd id="dMaterials">…</dd>'); add('Size', fmtSize(it.size)); add('Source', it.source); add('File', it.path);
    view.show(it);
  } else {
    $('#loading').hidden = true;
    view.clear();
    add('Level', levelLabel(it.level)); if (it.dims) add('Dimensions', `${it.dims[0]} × ${it.dims[1]}`);
    add('Mode', it.mode); add('Size', fmtSize(it.size)); add('Source', it.source);
    if (it.also_in?.length) add('Also in', [...new Set(it.also_in)].join(', '));
    add('File', it.path);
    showImage(it);
  }
  $('#dInfo').innerHTML = info.join('');
  fillLinks($('#dLinks'), it.path);
  $('#prevBtn').hidden = i <= 0; $('#nextBtn').hidden = i >= state.list.length - 1;
}
function showImage(it, c = $('#dControls'), onLoad) {
  const img = $('#bigImg'), cv = $('#bigCanvas');
  const btn = (k, v, l) => `<button class="toggle ${imgView[k] === v ? 'on' : ''}" data-k="${k}" data-v="${v}">${l}</button>`;
  c.innerHTML = `<div><label>Background</label><div class="row">${btn('bg', 'checker', 'Checker')}${btn('bg', 'black', 'Black')}${btn('bg', 'white', 'White')}</div></div>
    <div><label>Zoom</label><div class="row">${btn('zoom', 0, 'Fit')}${btn('zoom', 1, '1×')}${btn('zoom', 2, '2×')}${btn('zoom', 4, '4×')}</div></div>
    <div><label>Alpha channel</label><div class="row">${btn('alpha', true, 'Use alpha')}${btn('alpha', false, 'Ignore alpha')}</div></div>`;
  c.querySelectorAll('[data-k]').forEach((b) => b.onclick = () => {
    const k = b.dataset.k; imgView[k] = k === 'zoom' ? +b.dataset.v : k === 'alpha' ? b.dataset.v === 'true' : b.dataset.v;
    showImage(it, c, onLoad);
  });
  $('#viewImage').className = imgView.bg === 'checker' ? '' : imgView.bg;
  const apply = () => {
    const el = imgView.alpha ? img : cv;
    img.hidden = !imgView.alpha; cv.hidden = imgView.alpha;
    const stage = $('#stage');
    const w = img.naturalWidth, h = img.naturalHeight;
    const z = imgView.zoom || Math.max(0.1, Math.min((stage.clientWidth - 100) / w, (stage.clientHeight - 40) / h));
    el.style.width = w * z + 'px'; el.style.height = h * z + 'px';
    if (!imgView.alpha) {
      cv.width = w; cv.height = h;
      const g = cv.getContext('2d'); g.drawImage(img, 0, 0);
      const d = g.getImageData(0, 0, w, h); for (let p = 3; p < d.data.length; p += 4) d.data[p] = 255; g.putImageData(d, 0, 0);
    }
    onLoad?.();
  };
  const url = fileUrl(it.path);
  if (img.getAttribute('src') !== url) { img.onload = apply; img.src = url; } else if (img.complete) apply();
}
function closeDetail() { $('#overlay').hidden = true; view.clear(); detailIndex = -1; }
function step(d) {
  const i = detailIndex + d;
  if (i < 0 || i >= state.list.length) return;
  while (state.shown <= i) showMore();
  openDetail(i);
  document.querySelector(`#grid .card[data-i="${i}"]`)?.scrollIntoView({ block: 'nearest' });
}

// ---------------------------------------------------------------- events
$('#tabs').addEventListener('click', (e) => { const b = e.target.closest('button'); if (!b) return; state.tab = b.dataset.tab; state.chip = 'all'; refresh(); });
let searchTimer;
$('#search').addEventListener('input', (e) => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { state.q = e.target.value; refresh(); }, 150); });
$('#level').addEventListener('change', (e) => { state.level = state.pickedLevel = e.target.value; refresh(); });
$('#sort').addEventListener('change', (e) => { state.sort = e.target.value; refresh(); });
$('#chips').addEventListener('click', (e) => { const b = e.target.closest('.chip'); if (!b) return; state.chip = b.dataset.chip; refresh(); });
$('#cardSize').addEventListener('input', (e) => { document.documentElement.style.setProperty('--card', e.target.value + 'px'); try { localStorage.setItem('btgCard', e.target.value); } catch {} });
$('#renderAll').addEventListener('click', () => thumbs.renderAll());
$('#closeBtn').onclick = closeDetail;
$('#backToModel').onclick = backToModel;
$('#dTabs').addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) showPane(b.dataset.pane); });
$('#prevBtn').onclick = () => step(-1);
$('#nextBtn').onclick = () => step(1);
$('#overlay').addEventListener('click', (e) => { if (e.target.id === 'overlay') closeDetail(); });
document.addEventListener('keydown', (e) => {
  if (['INPUT', 'SELECT', 'TEXTAREA'].includes(e.target.tagName) && e.target.type !== 'range') return;
  if ($('#overlay').hidden) { if (e.key === '/') { e.preventDefault(); $('#search').focus(); } return; }
  if (e.key === 'Escape') { if (!$('#paneTexView').hidden) backToModel(); else closeDetail(); }
  else if (e.key === 'ArrowLeft') step(-1);
  else if (e.key === 'ArrowRight') step(1);
  else if (e.key === ' ') { e.preventDefault(); view.togglePlay(); }
});

try { const s = localStorage.getItem('btgCard'); if (s) { $('#cardSize').value = s; document.documentElement.style.setProperty('--card', s + 'px'); } } catch {}
readHash();
loadIndex().then(refresh).catch((e) => { $('#status').textContent = 'Could not load the index: ' + e.message; });
