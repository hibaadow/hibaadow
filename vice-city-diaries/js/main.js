// THE VICE CITY DIARIES — Episode 1. Unofficial fan-made animation.
// Real-time 3D (Three.js): procedural city, rigged procedural characters, cars, camera work, post-processing.
// Everything is driven by one clock (t, seconds) so the same scene plays live in the browser
// and renders frame-exact to MP4 (tools/render_mp4.cjs calls window.renderAt(t)).
import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';

const W = 1080, H = 1920, DUR = 90;
const params = new URLSearchParams(location.search);
const RENDER = params.has('render');
const QUALITY = RENDER ? 1 : Math.min(1, parseFloat(params.get('q') || (matchMedia('(max-width: 800px)').matches ? '0.5' : '0.75')));
if (RENDER) document.body.classList.add('render');

const EP = String(params.get('ep') || window.EP || '1'), E2 = EP === '2';
const TL = await (await fetch(E2 ? 'data/timeline_ep2.json' : 'data/timeline.json')).json();

// ---------------------------------------------------------------- helpers
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const lerp = (a, b, u) => a + (b - a) * u;
const ease = u => { u = clamp(u); return u * u * (3 - 2 * u); };
const eout = u => { u = clamp(u); return 1 - (1 - u) ** 3; };
const prog = (t, a, b) => clamp((t - a) / (b - a));
const v3 = (x, y, z) => new THREE.Vector3(x, y, z);
const V = (a, b, u) => a.clone().lerp(b, u);
function rng(seed) { return () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
const noise1 = (x) => Math.sin(x * 1.7) * 0.5 + Math.sin(x * 2.9 + 1.3) * 0.3 + Math.sin(x * 5.1 + 4.1) * 0.2;

// ---------------------------------------------------------------- renderer
const stage = document.getElementById('stage');
const sctx = stage.getContext('2d');
const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true, powerPreference: 'high-performance' });
renderer.setPixelRatio(1);
renderer.setSize(Math.round(W * QUALITY), Math.round(H * QUALITY), false);
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;
renderer.outputColorSpace = THREE.SRGBColorSpace;

const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2(0x1a0f2e, 0.0016);
const camera = new THREE.PerspectiveCamera(40, W / H, 0.05, 4000);

// sky
const skyMat = new THREE.ShaderMaterial({
  side: THREE.BackSide, depthWrite: false, fog: false,
  uniforms: { top: { value: new THREE.Color(0x04051a) }, mid: { value: new THREE.Color(0x2a0f45) }, horizon: { value: new THREE.Color(0xff5a7a) } },
  vertexShader: 'varying vec3 vP; void main(){ vP = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.); }',
  fragmentShader: `uniform vec3 top; uniform vec3 mid; uniform vec3 horizon; varying vec3 vP;
    void main(){ float h = vP.y; vec3 c = mix(horizon*0.75, mid, smoothstep(-0.02, 0.18, h)); c = mix(c, top, smoothstep(0.18, 0.6, h));
      c += horizon * 0.35 * exp(-abs(h) * 30.0); gl_FragColor = vec4(c, 1.); }`,
});
const sky = new THREE.Mesh(new THREE.SphereGeometry(3000, 32, 16), skyMat);
scene.add(sky);
{
  const r = rng(7), pts = [];
  for (let i = 0; i < 900; i++) { const a = r() * Math.PI * 2, e = 0.15 + r() * 1.3; pts.push(Math.cos(a) * Math.cos(e) * 2800, Math.sin(e) * 2800, Math.sin(a) * Math.cos(e) * 2800); }
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
  scene.add(new THREE.Points(g, new THREE.PointsMaterial({ color: 0xc8c8ff, size: 2.2, sizeAttenuation: false, fog: false, transparent: true, opacity: 0.7 })));
  const moon = new THREE.Mesh(new THREE.SphereGeometry(40, 24, 16), new THREE.MeshBasicMaterial({ color: new THREE.Color(1.6, 1.55, 1.4), fog: false }));
  moon.position.set(1800, 900, -1500); scene.add(moon);
}

// environment map for reflections: dusk sky + neon
{
  const pm = new THREE.PMREMGenerator(renderer);
  const env = new THREE.Scene();
  env.add(new THREE.Mesh(new THREE.SphereGeometry(100, 32, 16), skyMat));
  const neon = [[0xff2d78, 30, 8, 60], [0x22e1ff, -40, 10, 50], [0xffb347, 10, 4, -70], [0x9b5cff, -60, 12, -30]];
  for (const [c, x, y, z] of neon) { const m = new THREE.Mesh(new THREE.BoxGeometry(30, 4, 2), new THREE.MeshBasicMaterial({ color: new THREE.Color(c).multiplyScalar(4) })); m.position.set(x, y, z); m.lookAt(0, 0, 0); env.add(m); }
  scene.environment = pm.fromScene(env, 0.04).texture;
  scene.environmentIntensity = 0.6;
}

scene.add(new THREE.HemisphereLight(0x6a6ab0, 0x140a20, 0.5));
const keyLight = new THREE.PointLight(0xfff1e8, 2.0, 6, 1.2); keyLight.position.set(0.6, 0.4, 0.2); camera.add(keyLight);
const rimLight = new THREE.PointLight(0x7fb8ff, 1.4, 5, 1.2); rimLight.position.set(-0.8, 0.8, -2.2); camera.add(rimLight);
scene.add(camera);
const moonLight = new THREE.DirectionalLight(0x8fa8ff, 0.55); moonLight.position.set(300, 500, -200); scene.add(moonLight);

// ---------------------------------------------------------------- textures
function canvasTex(w, h, draw, srgb = true) {
  const c = document.createElement('canvas'); c.width = w; c.height = h; const g = c.getContext('2d'); draw(g, w, h);
  const t = new THREE.CanvasTexture(c); if (srgb) t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4; t.userData.canvas = c; t.userData.g = g; return t;
}
const winTex = canvasTex(256, 256, (g, w, h) => {
  const r = rng(11); g.fillStyle = '#0d0f1c'; g.fillRect(0, 0, w, h);
  for (let y = 0; y < 16; y++) for (let x = 0; x < 8; x++) {
    const lit = r(); let col = '#121528';
    if (lit > 0.55) col = ['#ffd9a0', '#ffe9c8', '#a8d8ff', '#ffc27a'][Math.floor(r() * 4)];
    else if (lit > 0.45) col = '#3a3150';
    g.fillStyle = col; g.fillRect(x * 32 + 6, y * 16 + 4, 20, 9);
  }
});
winTex.wrapS = winTex.wrapT = THREE.RepeatWrapping;

function signTex(text, color, font = 'Anton') {
  return canvasTex(512, 128, (g, w, h) => {
    g.clearRect(0, 0, w, h); g.font = `90px ${font}, Impact, sans-serif`; g.textAlign = 'center'; g.textBaseline = 'middle';
    g.shadowColor = color; g.shadowBlur = 18; g.fillStyle = color; g.fillText(text, w / 2, h / 2 + 4); g.shadowBlur = 0; g.fillStyle = '#fff'; g.globalAlpha = 0.65; g.fillText(text, w / 2, h / 2 + 4);
  });
}
const cashTex = canvasTex(256, 128, (g, w, h) => {
  g.fillStyle = '#7fae86'; g.fillRect(0, 0, w, h); g.strokeStyle = '#3e6b49'; g.lineWidth = 6; g.strokeRect(8, 8, w - 16, h - 16);
  g.fillStyle = '#2f5a3a'; g.beginPath(); g.ellipse(w / 2, h / 2, 34, 40, 0, 0, Math.PI * 2); g.fill();
  g.font = 'bold 34px Inter, sans-serif'; g.fillStyle = '#2f5a3a'; g.fillText('100', 20, 44); g.fillText('100', w - 86, h - 22);
});

// ---------------------------------------------------------------- materials
const M = {
  ground: new THREE.MeshStandardMaterial({ color: 0x0b0c14, roughness: 0.35, metalness: 0.3 }),
  road: new THREE.MeshStandardMaterial({ color: 0x101119, roughness: 0.25, metalness: 0.4 }),
  line: new THREE.MeshBasicMaterial({ color: 0x8c8ca0 }),
  sidewalk: new THREE.MeshStandardMaterial({ color: 0x2a2836, roughness: 0.7 }),
  sand: new THREE.MeshStandardMaterial({ color: 0x3b2f3a, roughness: 0.9 }),
  ocean: new THREE.MeshStandardMaterial({ color: 0x06122a, roughness: 0.12, metalness: 0.9 }),
  building: new THREE.MeshStandardMaterial({ map: winTex, emissiveMap: winTex, emissive: 0xffffff, emissiveIntensity: 1.25, roughness: 0.45, metalness: 0.4, vertexColors: true }),
  glass: new THREE.MeshPhysicalMaterial({ color: 0x0b2030, roughness: 0.05, metalness: 0.9, transparent: true, opacity: 0.45 }),
  rail: new THREE.MeshPhysicalMaterial({ color: 0x9fc4d8, roughness: 0.05, metalness: 0.2, transmission: 0, transparent: true, opacity: 0.18 }),
  steel: new THREE.MeshStandardMaterial({ color: 0x8a8fa2, roughness: 0.3, metalness: 0.9 }),
  concrete: new THREE.MeshStandardMaterial({ color: 0xd8d2c8, roughness: 0.8 }),
  trunk: new THREE.MeshStandardMaterial({ color: 0x4a3a30, roughness: 0.9 }),
  frond: new THREE.MeshStandardMaterial({ color: 0x1d4a34, roughness: 0.8, side: THREE.DoubleSide }),
  pole: new THREE.MeshStandardMaterial({ color: 0x1a1b24, roughness: 0.5, metalness: 0.6 }),
  lamp: new THREE.MeshBasicMaterial({ color: new THREE.Color(3.2, 2.4, 1.5) }),
  head: new THREE.MeshBasicMaterial({ color: new THREE.Color(3.5, 3.4, 3.1) }),
  tail: new THREE.MeshBasicMaterial({ color: new THREE.Color(4, 0.25, 0.3) }),
  paintBlack: new THREE.MeshPhysicalMaterial({ color: 0x17171f, metalness: 0.85, roughness: 0.28, clearcoat: 1, clearcoatRoughness: 0.08 }),
  paintSUV: new THREE.MeshPhysicalMaterial({ color: 0x101014, metalness: 0.7, roughness: 0.35, clearcoat: 0.8, clearcoatRoughness: 0.15 }),
  tint: new THREE.MeshPhysicalMaterial({ color: 0x05070c, metalness: 0.9, roughness: 0.05, transparent: true, opacity: 0.55 }),
  tire: new THREE.MeshStandardMaterial({ color: 0x0a0a0c, roughness: 0.9 }),
  rim: new THREE.MeshStandardMaterial({ color: 0x9a9aa8, metalness: 1, roughness: 0.25 }),
  interior: new THREE.MeshStandardMaterial({ color: 0x141317, roughness: 0.6 }),
  leatherSeat: new THREE.MeshStandardMaterial({ color: 0x2a1a17, roughness: 0.45 }),
  dashGlow: new THREE.MeshBasicMaterial({ color: new THREE.Color(0.4, 1.6, 2.2) }),
};

// ---------------------------------------------------------------- city
const city = new THREE.Group(); scene.add(city);
const HERO = v3(160, 0, -20);      // hero tower base (west face looks over the city)
const BALC_Y = 96;
{
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(4000, 4000), M.ground); ground.rotation.x = -Math.PI / 2; city.add(ground);
  const ocean = new THREE.Mesh(new THREE.PlaneGeometry(3000, 4000), M.ocean); ocean.rotation.x = -Math.PI / 2; ocean.position.set(1700, 0.05, 0); city.add(ocean);
  const sand = new THREE.Mesh(new THREE.PlaneGeometry(60, 4000), M.sand); sand.rotation.x = -Math.PI / 2; sand.position.set(230, 0.03, 0); city.add(sand);
  // moon path on the water
  const path = new THREE.Mesh(new THREE.PlaneGeometry(40, 900), new THREE.MeshBasicMaterial({ color: new THREE.Color(0.9, 0.85, 1.2), transparent: true, opacity: 0.18 }));
  path.rotation.x = -Math.PI / 2; path.rotation.z = 0.75; path.position.set(900, 0.1, -600); city.add(path);

  const r = rng(3), geos = [], BLOCK = 70, ROAD = 16;
  for (let gx = -8; gx <= 2; gx++) for (let gz = -9; gz <= 9; gz++) {
    const bx = gx * BLOCK, bz = gz * BLOCK;
    for (let k = 0; k < 3; k++) {
      const w = 14 + r() * 26, d = 14 + r() * 26;
      const dist = Math.hypot(bx - HERO.x, bz - HERO.z);
      const h = (12 + r() * 50) * (dist < 260 ? 1.8 : 1) + (r() > 0.92 ? 80 : 0);
      const x = bx + (r() - 0.5) * (BLOCK - ROAD - w), z = bz + (r() - 0.5) * (BLOCK - ROAD - d);
      if (Math.abs(x - HERO.x) < 50 && Math.abs(z - HERO.z) < 50) continue;
      const g = new THREE.BoxGeometry(w, h, d);
      const uv = g.attributes.uv, pos = g.attributes.position, nrm = g.attributes.normal;
      for (let i = 0; i < uv.count; i++) {
        const nx = Math.abs(nrm.getX(i)), ny = Math.abs(nrm.getY(i));
        if (ny > 0.5) { uv.setXY(i, 0.02, 0.02); continue; }
        const span = nx > 0.5 ? d : w;
        uv.setXY(i, uv.getX(i) * span / 24, uv.getY(i) * h / 32 + r() * 0);
      }
      const c = new THREE.Color().setHSL(0.62 + r() * 0.2, 0.25, 0.32 + r() * 0.25);
      const cols = []; for (let i = 0; i < pos.count; i++) cols.push(c.r, c.g, c.b);
      g.setAttribute('color', new THREE.Float32BufferAttribute(cols, 3));
      g.translate(x, h / 2, z); geos.push(g);
      if (r() > 0.8 && h > 40) {           // rooftop neon sign
        const words = ['HOTEL', 'OCEAN', 'PALMS', 'CLUB', 'LIQUOR', 'MOTEL', 'BAR', 'SUNSET'];
        const cols2 = ['#ff3d7f', '#22e1ff', '#ffb347', '#b46bff'];
        const s = new THREE.Mesh(new THREE.PlaneGeometry(18, 4.5), new THREE.MeshBasicMaterial({ map: signTex(words[Math.floor(r() * words.length)], cols2[Math.floor(r() * 4)]), transparent: true, color: new THREE.Color(2.2, 2.2, 2.2), depthWrite: false }));
        s.position.set(x, h + 3, z + d / 2 + 0.2); city.add(s);
      }
    }
  }
  city.add(new THREE.Mesh(mergeGeometries(geos), M.building));
  // roads with lane dashes
  for (let gx = -8; gx <= 3; gx++) {
    const rd = new THREE.Mesh(new THREE.PlaneGeometry(ROAD, 1400), M.road); rd.rotation.x = -Math.PI / 2; rd.position.set(gx * BLOCK + BLOCK / 2, 0.02, 0); city.add(rd);
  }
  for (let gz = -9; gz <= 9; gz++) {
    const rd = new THREE.Mesh(new THREE.PlaneGeometry(800, ROAD), M.road); rd.rotation.x = -Math.PI / 2; rd.position.set(-200, 0.025, gz * BLOCK + BLOCK / 2); city.add(rd);
  }
}

// palm trees (instanced)
function palmGeometry() {
  const parts = [];
  const trunk = new THREE.CylinderGeometry(0.22, 0.38, 9, 7, 6);
  const p = trunk.attributes.position;
  for (let i = 0; i < p.count; i++) { const y = p.getY(i) + 4.5; p.setX(i, p.getX(i) + 0.03 * y * y); }
  trunk.translate(0, 4.5, 0); trunk.setAttribute('color', new THREE.Float32BufferAttribute(new Array(p.count * 3).fill(0).map((_, k) => [0.29, 0.23, 0.19][k % 3]), 3));
  parts.push(trunk);
  for (let k = 0; k < 8; k++) {
    const f = new THREE.PlaneGeometry(0.9, 4.2, 1, 4);
    const fp = f.attributes.position;
    for (let i = 0; i < fp.count; i++) { const y = fp.getY(i) + 2.1; fp.setZ(i, -0.12 * y * y); fp.setX(i, fp.getX(i) * (1 - y / 4.6)); }
    f.translate(0, 2.1, 0); f.rotateX(-1.1); f.rotateY(k / 8 * Math.PI * 2); f.translate(0.03 * 81, 9, 0);
    f.setAttribute('color', new THREE.Float32BufferAttribute(new Array(fp.count * 3).fill(0).map((_, j) => [0.11, 0.3, 0.2][j % 3]), 3));
    parts.push(f);
  }
  const g = mergeGeometries(parts.map(x => x.toNonIndexed()));
  return g;
}
const palmGeo = palmGeometry();
const palmMat = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.85, side: THREE.DoubleSide });
function palms(list) {
  const m = new THREE.InstancedMesh(palmGeo, palmMat, list.length);
  m.userData.list = list; m.instanceMatrix.setUsage(THREE.DynamicDrawUsage); return m;
}
function updatePalms(m, t, offsetZ = 0, wrap = 0) {
  const o = new THREE.Object3D();
  m.userData.list.forEach((p, i) => {
    let z = p.z + offsetZ; if (wrap) z = ((z % wrap) + wrap * 1.5) % wrap - wrap / 2 + (p.zc || 0);
    o.position.set(p.x, 0, z); o.rotation.set(Math.sin(t * 0.9 + i) * 0.025, p.r, Math.sin(t * 1.3 + i * 2) * 0.03); o.scale.setScalar(p.s);
    o.updateMatrix(); m.setMatrixAt(i, o.matrix);
  });
  m.instanceMatrix.needsUpdate = true;
}
const boulevardPalms = palms(Array.from({ length: 60 }, (_, i) => ({ x: 130 + (i % 2) * 64, z: -600 + Math.floor(i / 2) * 40, r: i * 1.7, s: 1.2 + (i % 3) * 0.15 })));
city.add(boulevardPalms);

// city traffic (instanced cars as light pairs + bodies)
const TRAFFIC = 160;
const trafficBody = new THREE.InstancedMesh(new RoundedBoxGeometry(2, 1.3, 4.4, 2, 0.35), new THREE.MeshStandardMaterial({ color: 0x1b1d2a, metalness: 0.7, roughness: 0.35 }), TRAFFIC);
const trafficHead = new THREE.InstancedMesh(new THREE.BoxGeometry(1.8, 0.25, 0.1), M.head, TRAFFIC);
const trafficTail = new THREE.InstancedMesh(new THREE.BoxGeometry(1.8, 0.25, 0.1), M.tail, TRAFFIC);
[trafficBody, trafficHead, trafficTail].forEach(m => { m.instanceMatrix.setUsage(THREE.DynamicDrawUsage); city.add(m); });
const trafficLanes = (() => { const r = rng(21); return Array.from({ length: TRAFFIC }, () => ({ along: r() > 0.5, lane: Math.floor(r() * 11) - 8, side: r() > 0.5 ? 1 : -1, phase: r() * 1400, speed: 9 + r() * 10 })); })();
function updateTraffic(t) {
  const o = new THREE.Object3D(), BLOCK = 70;
  trafficLanes.forEach((c, i) => {
    const s = ((c.phase + t * c.speed * c.side) % 1400 + 1400) % 1400 - 700;
    if (c.along) { o.position.set(c.lane * BLOCK + BLOCK / 2 + c.side * 3.5, 0.7, s); o.rotation.set(0, c.side > 0 ? 0 : Math.PI, 0); }
    else { o.position.set(s * 0.55 - 220, 0.7, (c.lane + 1) * BLOCK + BLOCK / 2 + c.side * 3.5); o.rotation.set(0, c.side > 0 ? Math.PI / 2 : -Math.PI / 2, 0); }
    o.updateMatrix(); trafficBody.setMatrixAt(i, o.matrix);
    const f = new THREE.Object3D(); f.position.copy(o.position); f.rotation.copy(o.rotation); f.translateZ(2.25); f.updateMatrix(); trafficHead.setMatrixAt(i, f.matrix);
    f.translateZ(-4.5); f.updateMatrix(); trafficTail.setMatrixAt(i, f.matrix);
  });
  [trafficBody, trafficHead, trafficTail].forEach(m => (m.instanceMatrix.needsUpdate = true));
}

// street lamps along the boulevard
{
  const n = 40, poles = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.12, 0.16, 8, 6), M.pole, n), bulbs = new THREE.InstancedMesh(new THREE.SphereGeometry(0.35, 8, 6), M.lamp, n);
  const o = new THREE.Object3D();
  for (let i = 0; i < n; i++) { o.position.set(140 + (i % 2) * 44, 4, -600 + Math.floor(i / 2) * 60); o.updateMatrix(); poles.setMatrixAt(i, o.matrix); o.position.y = 8.1; o.updateMatrix(); bulbs.setMatrixAt(i, o.matrix); }
  city.add(poles, bulbs);
}

// hero tower + balcony + entrance
const balcony = new THREE.Group();
{
  const tw = new THREE.Mesh(new THREE.BoxGeometry(44, 150, 44), new THREE.MeshStandardMaterial({ color: 0x18303d, map: winTex, emissiveMap: winTex, emissive: 0xffffff, emissiveIntensity: 1.1, roughness: 0.15, metalness: 0.8 }));
  tw.geometry.attributes.uv.array.forEach((v, i, a) => { a[i] = v * (i % 2 ? 150 / 32 : 44 / 24); });
  tw.position.set(HERO.x + 22, 75, HERO.z); city.add(tw);
  const crown = new THREE.Mesh(new THREE.BoxGeometry(46, 2, 46), new THREE.MeshBasicMaterial({ color: new THREE.Color(0.4, 2.2, 2.6) })); crown.position.set(HERO.x + 22, 150, HERO.z); city.add(crown);
  for (let k = 0; k < 14; k++) {   // balcony slabs up the west face
    const s = new THREE.Mesh(new THREE.BoxGeometry(6, 0.4, 16), M.concrete); s.position.set(HERO.x - 3, 12 + k * 7, HERO.z + ((k % 2) * 2 - 1) * 8); city.add(s);
  }
  // hero balcony (Lucia's)
  balcony.position.set(HERO.x, BALC_Y, HERO.z); city.add(balcony);
  const slab = new THREE.Mesh(new THREE.BoxGeometry(8, 0.35, 12), M.concrete); slab.position.set(-1, -0.18, 0); balcony.add(slab);
  const glassRail = new THREE.Mesh(new THREE.BoxGeometry(0.04, 1.05, 12), M.rail); glassRail.position.set(-4.95, 0.55, 0); balcony.add(glassRail);
  const top = new THREE.Mesh(new THREE.BoxGeometry(0.08, 0.06, 12), M.steel); top.position.set(-4.95, 1.1, 0); balcony.add(top);
  const door = new THREE.Mesh(new THREE.PlaneGeometry(10, 3.2), new THREE.MeshBasicMaterial({ color: new THREE.Color(0.55, 0.4, 0.28) })); door.rotation.y = -Math.PI / 2; door.position.set(2.9, 1.6, 0); balcony.add(door);
  const warm = new THREE.PointLight(0xffb070, 6, 10, 1.6); warm.position.set(1.5, 2.2, 0); balcony.add(warm);
  const table = new THREE.Group(); table.position.set(-2.4, 0, 2.2); balcony.add(table);
  const ttop = new THREE.Mesh(new THREE.CylinderGeometry(0.45, 0.45, 0.04, 24), M.steel); ttop.position.y = 0.72; table.add(ttop);
  const tleg = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.04, 0.72, 8), M.steel); tleg.position.y = 0.36; table.add(tleg);
  const pack = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.02, 0.09), new THREE.MeshStandardMaterial({ color: 0xe9e4da })); pack.position.set(0.15, 0.75, -0.1); table.add(pack);
  balcony.userData.table = table;
  // entrance at street level
  const canopy = new THREE.Mesh(new THREE.BoxGeometry(5, 0.3, 12), M.concrete); canopy.position.set(HERO.x - 3, 4, HERO.z); city.add(canopy);
  const strip = new THREE.Mesh(new THREE.BoxGeometry(5.05, 0.08, 12.05), new THREE.MeshBasicMaterial({ color: new THREE.Color(1.3, 0.95, 0.6) })); strip.position.set(HERO.x - 3, 3.83, HERO.z); city.add(strip);
  const lobby = new THREE.Mesh(new THREE.PlaneGeometry(10, 3.6), new THREE.MeshBasicMaterial({ color: new THREE.Color(0.55, 0.42, 0.3) })); lobby.rotation.y = -Math.PI / 2; lobby.position.set(HERO.x - 0.05, 1.8, HERO.z); city.add(lobby);
  const entLight = new THREE.PointLight(0xffc27a, 10, 18, 1.5); entLight.position.set(HERO.x - 4, 3.4, HERO.z); city.add(entLight);
  const sw = new THREE.Mesh(new THREE.BoxGeometry(10, 0.2, 400), M.sidewalk); sw.position.set(HERO.x - 5, 0.1, HERO.z); city.add(sw);
}
const cig = new THREE.Mesh(new THREE.CylinderGeometry(0.004, 0.004, 0.085, 6), new THREE.MeshStandardMaterial({ color: 0xf5f2ea }));
cig.rotation.z = Math.PI / 2;

// ---------------------------------------------------------------- characters
// ---- sculpted anatomy helpers (all procedural, original designs)
function sculptHead(F, skinHex, lipHex, hairHex, inHair) {
  const g = new THREE.SphereGeometry(0.1, 176, 132), p = g.attributes.position, n = p.count;
  const b = (x, y, z, cx, cy, cz, r) => Math.exp(-((x - cx) ** 2 + (y - cy) ** 2 + (z - cz) ** 2) / (r * r));
  const b2 = (x, y, cx, cy, rx, ry) => Math.exp(-(((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2));
  const sm = (a, c, x) => { const u = clamp((x - a) / (c - a)); return u * u * (3 - 2 * u); };
  const YL = -0.071;                                     // lip line
  const col = new Float32Array(n * 3), jaw = new Float32Array(n);
  const skin = new THREE.Color(skinHex), lip = new THREE.Color(lipHex), hair = new THREE.Color(hairHex), c = new THREE.Color();
  const dark = new THREE.Color(0x1a0807), brow = new THREE.Color(hairHex).multiplyScalar(0.9), blush = new THREE.Color(0xc0605a);
  for (let i = 0; i < n; i++) {
    let x = p.getX(i), y = p.getY(i), z = p.getZ(i);
    const ny = y / 0.1, nz = z / 0.1;
    x *= F ? 0.76 : 0.79; y *= 1.08; z *= 0.98;
    if (nz < 0) z *= 1 + 0.14 * -nz * clamp(ny + 0.6);                                   // occiput
    if (ny < 0.1) {                                                                       // jaw + chin
      const k = clamp((0.1 - ny) / 1.1);
      x *= 1 - (F ? 0.4 : 0.3) * k ** 1.4;
      if (z < 0) z *= 1 - 0.55 * k ** 1.2; else z = z * (1 - 0.08 * k) + 0.006 * k;
    }
    const front = sm(0.3, 0.75, nz);
    if (nz > 0.2) z -= (nz - 0.2) * 0.014;                                                // face plane
    for (const sx of [-1, 1]) {
      z -= 0.007 * b(x, y, z, sx * 0.031, 0.0, 0.088, 0.017);                             // eye sockets
      const cb = b(x, y, z, sx * 0.046, -0.026, 0.07, 0.024); x += sx * 0.004 * cb; z += (F ? 0.006 : 0.004) * cb;   // cheekbones
      if (!F) { const j = b(x, y, z, sx * 0.05, -0.083, 0.045, 0.025); x += sx * 0.005 * j; }
      z -= 0.0035 * b(x, y, z, sx * 0.03, -0.06, 0.082, 0.012) * front;                    // nasolabial softness
    }
    z += (F ? 0.002 : 0.005) * b(x, y, z, 0, 0.018, 0.092, 0.035);                        // brow ridge
    z += 0.006 * b(x, y, z, 0, -0.103, 0.07, 0.024);                                       // chin
    z += 0.006 * b(x, y, z, 0, -0.07, 0.085, 0.026);                                       // muzzle
    // nose: bridge -> tip, alae
    if (y < 0.016 && y > -0.06) {
      const t = clamp((0.014 - y) / 0.058), sg = (F ? 0.0052 : 0.0062) + 0.0042 * t;
      const h = (0.003 + (F ? 0.016 : 0.018) * t ** 1.7) * sm(-0.057, -0.045, y) * sm(0.016, 0.004, y);
      z += h * Math.exp(-(x * x) / (2 * sg * sg)) * front;
    }
    for (const sx of [-1, 1]) z += 0.0065 * b2(x, y, sx * (F ? 0.0105 : 0.012), -0.049, 0.0065, 0.0055) * front;
    // lips
    const lw = F ? 0.021 : 0.022, lx = Math.exp(-((x / lw) ** 4));
    z += lx * front * ((F ? 0.0042 : 0.0032) * b2(x, y, 0, YL + 0.0045, 1, 0.0042) + (F ? 0.0048 : 0.0042) * b2(x, y, 0, YL - 0.005, 1, 0.005));
    z -= 0.002 * lx * front * b2(x, y, 0, YL, 1, 0.0012);
    // paint
    c.copy(skin);
    const lipMask = lx * front * (sm(YL + 0.0105, YL + 0.006, y) * sm(YL - 0.012, YL - 0.0075, y)) * (1 - 0.6 * sm(0.006, 0, Math.abs(x)) * b2(x, y, 0, YL + 0.009, 1, 0.002));
    c.lerp(lip, clamp(lipMask * 0.95));
    for (const sx of [-1, 1]) {
      c.lerp(dark, 0.55 * b2(x, y, sx * 0.0075, -0.0545, 0.0035, 0.0018) * front);          // nostrils
      if (F) c.lerp(blush, 0.18 * b2(x, y, sx * 0.045, -0.035, 0.018, 0.014) * front);
      c.lerp(new THREE.Color(0x3a2620), 0.25 * b2(x, y, sx * 0.031, 0.012, 0.016, 0.006) * front);   // lid crease shadow
    }
    if (!F) {                                                                              // short beard + moustache
      const cheekLine = -0.035 - 0.02 * sm(0.06, 0.03, Math.abs(x));
      let bm = sm(cheekLine + 0.004, cheekLine - 0.006, y) * sm(-0.13, -0.11, y) * sm(-0.035, 0.0, z);
      bm = Math.max(bm, sm(0.026, 0.02, Math.abs(x)) * sm(YL + 0.006, YL + 0.009, y) * sm(YL + 0.019, YL + 0.014, y) * front);
      bm *= 1 - lipMask;
      c.lerp(new THREE.Color(0x1c140f), clamp(bm * 0.95));
      if (bm > 0.01) { const nn = v3(x, y * 0.8, z).normalize(); x += nn.x * 0.003 * bm; y += nn.y * 0.003 * bm; z += nn.z * 0.003 * bm; }
    }
    const hm = inHair(x, y, z) ? 1 : 0;
    c.lerp(hair, hm * 0.9);
    col[i * 3] = c.r; col[i * 3 + 1] = c.g; col[i * 3 + 2] = c.b;
    // mouth slit (dark band squashed shut at rest) + jaw weights for speech
    const inMouth = Math.exp(-((x / (lw * 0.95)) ** 6)) * front;
    if (inMouth > 0.2 && Math.abs(y - YL) < 0.0032) { c.copy(dark); col[i * 3] = c.r; col[i * 3 + 1] = c.g; col[i * 3 + 2] = c.b; y = YL + (y - YL) * 0.12; }
    jaw[i] = sm(YL + 0.0005, YL - 0.008, y) * sm(-0.02, 0.03, z) * (0.55 + 0.45 * inMouth);
    p.setXYZ(i, x, y, z);
  }
  g.setAttribute('color', new THREE.BufferAttribute(col, 3));
  g.computeVertexNormals();
  g.userData.rest = p.array.slice(); g.userData.jaw = jaw; g.userData.YL = YL;
  return g;
}
function subGeo(geo, test, s) {            // keep the triangles whose vertices all pass test, scaled out by s
  const p = geo.attributes.position, n = geo.attributes.normal, idx = geo.index.array, keep = [];
  for (let i = 0; i < idx.length; i += 3) {
    let ok = true;
    for (let k = 0; k < 3; k++) { const v = idx[i + k]; if (!test(p.getX(v), p.getY(v), p.getZ(v))) { ok = false; break; } }
    if (ok) keep.push(idx[i], idx[i + 1], idx[i + 2]);
  }
  const g = new THREE.BufferGeometry(), pos = new Float32Array(p.count * 3);
  for (let i = 0; i < p.count; i++) { pos[i * 3] = p.getX(i) * s; pos[i * 3 + 1] = p.getY(i) * s; pos[i * 3 + 2] = p.getZ(i) * s; }
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3)); g.setAttribute('normal', n.clone()); g.setIndex(keep);
  return g;
}
function hairStrands(headGeo, F, inHair) {
  const r = rng(F ? 41 : 77), p = headGeo.attributes.position, roots = [];
  for (let i = 0; i < p.count; i++) { const x = p.getX(i), y = p.getY(i), z = p.getZ(i); if (inHair(x, y, z) && y > (F ? -0.03 : 0.035)) roots.push(v3(x, y, z)); }
  const geos = [], N = F ? 1100 : 1400;
  const shell = (d, s) => { const k = Math.sqrt((d.x / 0.08) ** 2 + (d.y / 0.113) ** 2 + (d.z / (d.z < 0 ? 0.112 : 0.1)) ** 2); return d.clone().multiplyScalar(s / k); };
  for (let n = 0; n < N; n++) {
    const root = roots[Math.floor(r() * roots.length)].clone().add(v3((r() - .5) * .004, (r() - .5) * .004, (r() - .5) * .004));
    const pts = [root.clone().multiplyScalar(0.99)];
    if (F) {
      const side = Math.abs(root.x) < 0.003 ? (r() < .5 ? -1 : 1) : Math.sign(root.x);
      const ang = Math.atan2(Math.abs(root.x), root.z);
      const framing = root.z > 0.02 && r() < 0.12;
      const drop = side * (framing ? 1.35 + r() * 0.15 : lerp(1.95, 3.1, ang / Math.PI) + (r() - .5) * 0.15);
      const el = framing ? -0.15 : -0.4;
      const D = v3(Math.sin(drop) * Math.cos(el), Math.sin(el), Math.cos(drop) * Math.cos(el));
      const R0 = root.clone().normalize();
      for (let k = 1; k <= 5; k++) { const d = R0.clone().lerp(D, k / 5).normalize(); pts.push(shell(d, 1.06 + 0.04 * k / 5 + r() * 0.012)); }
      const last = pts[pts.length - 1], wv = r() * 6.28, amp = 0.006 + r() * 0.006;
      if (framing) {
        pts.push(v3(last.x * 1.08, -0.07, last.z + 0.006), v3(last.x * 1.05 + side * 0.006, -0.11 - r() * 0.02, last.z + 0.004));
      } else {
        const L = 0.2 + r() * 0.06, X = last.x * 1.02;
        pts.push(v3(X * 1.05, -0.1, Math.min(last.z, -0.05) * 1.15));
        pts.push(v3(X * 1.02 + side * 0.008, -0.165, Math.min(last.z * 1.4, -0.14)));
        for (let k = 1; k <= 3; k++) { const y = -0.165 - L * k / 3; pts.push(v3(X * (1 + 0.1 * k / 3) + Math.sin(wv + k * 1.9) * amp, y, -0.15 - 0.006 * k + Math.cos(wv + k * 1.7) * 0.004)); }
      }
    } else {
      const nrm = root.clone().normalize(), back = v3(0, 0.3, -1).normalize();
      const top = clamp((root.y - 0.035) / 0.07), len = 0.008 + 0.02 * top + r() * 0.006;
      const tipDir = nrm.clone().multiplyScalar(0.6).add(back.multiplyScalar(0.7 * top + 0.2)).add(v3((r() - .5) * .5, 0, (r() - .5) * .5)).normalize();
      pts.push(root.clone().addScaledVector(nrm, 0.006).addScaledVector(tipDir, len * 0.4), root.clone().addScaledVector(nrm, 0.007).addScaledVector(tipDir, len));
    }
    const curve = new THREE.CatmullRomCurve3(pts);
    geos.push(new THREE.TubeGeometry(curve, F ? 22 : 4, F ? 0.0026 : 0.0024, 3, false));
  }
  if (F) { const sheet = new RoundedBoxGeometry(0.17, 0.25, 0.022, 3, 0.01); sheet.translate(0, -0.27, -0.148); geos.push(sheet.toNonIndexed().index ? sheet : sheet); }
  return mergeGeometries(geos.map(g => g.index ? g.toNonIndexed() : g));
}
function torsoGeo(F) {
  const g = new THREE.CylinderGeometry(1, 1, 0.5, 48, 24), p = g.attributes.position;
  const W = F ? [[0, .155], [.3, .122], [.55, .138], [.72, .15], [.9, .165], [1, .07]] : [[0, .16], [.3, .155], [.6, .18], [.8, .195], [.92, .2], [1, .085]];
  const Dp = F ? [[0, .095], [.3, .08], [.55, .1], [.68, .11], [.9, .085], [1, .05]] : [[0, .1], [.3, .1], [.6, .112], [.8, .108], [.92, .095], [1, .055]];
  const at = (tab, u) => { for (let i = 1; i < tab.length; i++) if (u <= tab[i][0]) { const [a, va] = tab[i - 1], [b, vb] = tab[i]; const k = (u - a) / (b - a); return lerp(va, vb, k * k * (3 - 2 * k)); } return tab[tab.length - 1][1]; };
  for (let i = 0; i < p.count; i++) {
    const x = p.getX(i), y = p.getY(i), z = p.getZ(i), u = y / 0.5 + 0.5, a = Math.atan2(z, x);
    const c = Math.cos(a), s = Math.sin(a);
    const se = (v, e) => Math.sign(v) * Math.abs(v) ** e;
    const r = Math.hypot(x, z) > 0.5 ? 1 : Math.hypot(x, z);
    p.setXYZ(i, se(c, 0.75) * at(W, u) * r, y + 0.25, se(s, 0.8) * at(Dp, u) * r - (u > 0.6 && s < 0 ? 0.008 : 0));
  }
  g.computeVertexNormals(); return g;
}
function capsule(r, len, mat) { const m = new THREE.Mesh(new THREE.CapsuleGeometry(r, len, 6, 12), mat); return m; }
function joint(parent, x, y, z) { const j = new THREE.Group(); j.position.set(x, y, z); parent.add(j); return j; }
function makeHuman(spec) {
  const S = spec.scale || 1, F = !!spec.female;
  const root = new THREE.Group(); root.scale.setScalar(S);
  const skin = new THREE.MeshPhysicalMaterial({ color: spec.skin, roughness: 0.52, sheen: 0.35, sheenColor: new THREE.Color(0xff9a80), sheenRoughness: 0.5 });
  const top = new THREE.MeshStandardMaterial({ color: spec.jacket, roughness: spec.jacketRough ?? 0.45, metalness: spec.jacketMetal ?? 0.05 });
  const shirt = new THREE.MeshStandardMaterial({ color: spec.shirt, roughness: 0.7 });
  const legs = new THREE.MeshStandardMaterial({ color: spec.pants, roughness: 0.75 });
  const shoes = new THREE.MeshStandardMaterial({ color: spec.shoes, roughness: 0.5 });
  const J = {};
  J.hips = joint(root, 0, 0.94, 0);
  const pelvis = new THREE.Mesh(new RoundedBoxGeometry(F ? 0.31 : 0.32, 0.18, 0.19, 3, 0.07), legs); J.hips.add(pelvis);
  J.spine = joint(J.hips, 0, 0.06, 0);
  const torso = new THREE.Mesh(torsoGeo(F), top); J.spine.add(torso);
  const front = new THREE.Mesh(new RoundedBoxGeometry(0.12, 0.38, 0.02, 2, 0.008), shirt); front.position.set(0, 0.29, 0.106); J.spine.add(front);
  for (const sx of [-1, 1]) { const lap = new THREE.Mesh(new THREE.BoxGeometry(0.035, 0.36, 0.015), top); lap.position.set(sx * 0.075, 0.3, 0.112); lap.rotation.z = sx * 0.18; J.spine.add(lap); }
  J.neck = joint(J.spine, 0, 0.5, 0);
  const neck = capsule(F ? 0.035 : 0.046, 0.06, skin); neck.position.y = 0.04; J.neck.add(neck);
  J.head = joint(J.neck, 0, 0.11, 0.014);
  // sculpted head with life-size features; hg = head-geometry space (centre of the skull)
  const hg = new THREE.Group(); hg.position.set(0, 0.04, 0); J.head.add(hg);
  const inHair = F ? (x, y, z) => (y > 0.064 - 0.12 * clamp(-z / 0.1) || z < -0.03 && y > -0.07) && !(Math.abs(x) > 0.055 && y < 0.03 && z > -0.035)
                   : (x, y, z) => y > 0.06 - 0.08 * clamp(-z / 0.05) || z < -0.04 && y > -0.06 || Math.abs(x) > 0.058 && y > -0.025 && z < 0.025;
  const headGeo = sculptHead(F, spec.skin, spec.lips, spec.hair, inHair);
  const headSkin = skin.clone(); headSkin.color.set(0xffffff); headSkin.vertexColors = true;
  hg.add(new THREE.Mesh(headGeo, headSkin));
  const probe = new THREE.Mesh(headGeo); probe.updateMatrixWorld(true);
  const ray = new THREE.Raycaster();
  const surf = (x, y) => { ray.set(v3(x, y, 0.3), v3(0, 0, -1)); const h = ray.intersectObject(probe)[0]; return h ? h.point.z : 0.08; };
  for (const sx of [-1, 1]) { const ear = new THREE.Mesh(new THREE.SphereGeometry(0.02, 12, 10), skin); ear.scale.set(0.38, 1.3, 0.75); ear.position.set(sx * 0.069, -0.022, -0.014); ear.rotation.y = sx * 0.45; hg.add(ear); }
  // eyes, lids, lashes, brows
  const face = { eyes: [], irises: [], brows: [], F };
  const white = new THREE.MeshPhysicalMaterial({ color: 0xe2d8cf, roughness: 0.12, clearcoat: 1 });
  const irisM = new THREE.MeshStandardMaterial({ color: spec.eyes || 0x2a1a10, roughness: 0.15 });
  const browM = new THREE.MeshStandardMaterial({ color: spec.brow || spec.hair, roughness: 0.9, transparent: true, opacity: 0.85 });
  const lashM = new THREE.MeshBasicMaterial({ color: 0x0c0806 });
  const EX = 0.0315, EY = -0.002, ER = 0.0118;
  for (const sx of [-1, 1]) {
    const e = new THREE.Group(); e.position.set(sx * EX, EY, surf(sx * EX, EY) - ER * 0.5); hg.add(e);
    e.add(new THREE.Mesh(new THREE.SphereGeometry(ER, 20, 16), white));
    const ig = new THREE.Group(); e.add(ig);
    const ir = new THREE.Mesh(new THREE.SphereGeometry(ER * 0.47, 16, 12), irisM); ir.scale.z = 0.45; ir.position.z = ER * 0.9; ig.add(ir);
    const pup = new THREE.Mesh(new THREE.CircleGeometry(ER * 0.2, 16), new THREE.MeshBasicMaterial({ color: 0x030202 })); pup.position.z = ER * 0.47 + 0.0002; ir.add(pup);
    const glint = new THREE.Mesh(new THREE.CircleGeometry(ER * 0.07, 8), new THREE.MeshBasicMaterial({ color: 0xffffff })); glint.scale.setScalar(0.7); glint.position.set(ER * 0.13, ER * 0.15, ER * 0.47 + 0.0004); ir.add(glint);
    const lid = new THREE.Group(); e.add(lid);
    const lm = new THREE.Mesh(new THREE.SphereGeometry(ER * 1.1, 20, 12, 0, Math.PI * 2, 0, Math.PI / 2), skin); lm.rotation.x = Math.PI / 2; lid.add(lm);
    const lash = new THREE.Mesh(new THREE.TorusGeometry(ER * 1.1, F ? 0.0013 : 0.0008, 6, 20, Math.PI), lashM); lash.rotation.z = Math.PI; lid.add(lash);
    const low = new THREE.Mesh(new THREE.SphereGeometry(ER * 1.07, 20, 8, 0, Math.PI * 2, Math.PI - 0.62, 0.62), skin); low.rotation.x = -0.52; e.add(low);
    const pts = [];
    for (let k = 0; k <= 6; k++) { const u = k / 6, bx = sx * (0.013 + u * 0.035), by = 0.018 + Math.sin(u * Math.PI * 0.85) * (F ? 0.007 : 0.0035) - u * 0.003; pts.push(v3(bx, by, surf(bx, by) + 0.0012)); }
    const bg = new THREE.Group(); hg.add(bg);
    const br = new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), 16, F ? 0.0016 : 0.0024, 5), browM); bg.add(br);
    face.eyes.push({ e, lid }); face.irises.push(ig); face.brows.push(bg);
  }
  face.geo = headGeo;
  const hairM = new THREE.MeshStandardMaterial({ color: spec.hair, roughness: 0.4, metalness: 0.1 });
  hg.add(new THREE.Mesh(hairStrands(headGeo, F, inHair), hairM));
  if (spec.earrings) for (const sx of [-1, 1]) { const ring = new THREE.Mesh(new THREE.TorusGeometry(0.013, 0.0018, 8, 24), new THREE.MeshStandardMaterial({ color: 0xd4a640, metalness: 1, roughness: 0.2 })); ring.position.set(sx * 0.078, -0.052, -0.01); ring.rotation.y = Math.PI / 2; hg.add(ring); }
  if (spec.chain) { const ch = new THREE.Mesh(new THREE.TorusGeometry(0.07, 0.0025, 6, 48), new THREE.MeshStandardMaterial({ color: 0xd9ad48, metalness: 1, roughness: 0.18 })); ch.scale.set(1, 1.2, 1); ch.rotation.x = Math.PI / 2 - 0.45; ch.position.set(0, 0.45, 0.04); J.spine.add(ch); }
  // arms
  for (const [side, sx] of [['L', 1], ['R', -1]]) {
    const sh = joint(J.spine, sx * (spec.chestW / 2 + 0.01), 0.45, 0); J['sh' + side] = sh;
    const ua = capsule(0.047, 0.22, top); ua.position.y = -0.14; sh.add(ua);
    const el = joint(sh, 0, -0.29, 0); J['el' + side] = el;
    const fa = capsule(0.04, 0.2, top); fa.position.y = -0.12; el.add(fa);
    const cuff = capsule(0.033, 0.04, skin); cuff.position.y = -0.245; el.add(cuff);
    const hand = joint(el, 0, -0.28, 0); J['hand' + side] = hand;
    const hm = new THREE.Mesh(new RoundedBoxGeometry(0.06, 0.09, 0.03, 2, 0.012), skin); hm.position.y = -0.03; hand.add(hm);
  }
  for (const [side, sx] of [['L', 1], ['R', -1]]) {
    const th = joint(J.hips, sx * 0.09, -0.04, 0); J['th' + side] = th;
    const tm = capsule(0.068, 0.32, legs); tm.position.y = -0.21; th.add(tm);
    const kn = joint(th, 0, -0.44, 0); J['kn' + side] = kn;
    const sm = capsule(0.054, 0.32, legs); sm.position.y = -0.2; kn.add(sm);
    const ft = joint(kn, 0, -0.43, 0); J['ft' + side] = ft;
    const sho = new THREE.Mesh(new RoundedBoxGeometry(0.09, 0.07, 0.24, 2, 0.03), shoes); sho.position.set(0, -0.03, 0.05); ft.add(sho);
  }
  const h = { root, J, face, spec, mouthOpen: 0 };
  setPose(h, {});
  return h;
}
// pose = { spine:[x,y,z], head:[x,y,z], shL:[x,y,z], elL:x, shR, elR, thL:[x,y,z], knL:x, thR, knR, hips:[x,y,z], hipY }
function setPose(h, p) {
  const J = h.J;
  const r = (o, a) => o.rotation.set(a?.[0] || 0, a?.[1] || 0, a?.[2] || 0);
  r(J.hips, p.hips); J.hips.position.y = p.hipY ?? 0.94;
  r(J.spine, p.spine); r(J.neck, p.neck); r(J.head, p.head);
  r(J.shL, p.shL || [0, 0, 0.08]); J.elL.rotation.set(p.elL ?? -0.15, 0, 0);
  r(J.shR, p.shR || [0, 0, -0.08]); J.elR.rotation.set(p.elR ?? -0.15, 0, 0);
  r(J.handL, p.handL); r(J.handR, p.handR);
  r(J.thL, p.thL); J.knL.rotation.set(p.knL ?? 0, 0, 0); r(J.thR, p.thR); J.knR.rotation.set(p.knR ?? 0, 0, 0);
  J.ftL.rotation.set(p.ftL ?? 0, 0, 0); J.ftR.rotation.set(p.ftR ?? 0, 0, 0);
}
function setFace(h, { mouth = 0, blink = 0, look = [0, 0], brow = 0, smirk = 0 }) {
  const f = h.face, o = clamp(mouth), g = f.geo;
  const key = Math.round(o * 40) + ':' + Math.round(smirk * 20);
  if (f.mkey !== key) {
    f.mkey = key;
    const p = g.attributes.position.array, R = g.userData.rest, jw = g.userData.jaw, YL = g.userData.YL;
    for (let i = 0, n = jw.length; i < n; i++) {
      const w = jw[i]; let y = R[i * 3 + 1], z = R[i * 3 + 2];
      if (w > 0) { y -= w * o * 0.011; z -= w * o * 0.002; }
      if (smirk && z > 0.06 && Math.abs(R[i * 3 + 1] - YL) < 0.012) y += smirk * 0.003 * Math.exp(-(((R[i * 3] - 0.02) / 0.008) ** 2));
      p[i * 3 + 1] = y; p[i * 3 + 2] = z;
    }
    g.attributes.position.needsUpdate = true;
  }
  f.eyes.forEach(({ lid }) => { lid.rotation.x = -lerp(2.0, 0.55, clamp(blink)); });
  f.irises.forEach(ig => { ig.rotation.y = look[0] * 0.35; ig.rotation.x = -look[1] * 0.25; });
  f.brows.forEach((b, i) => { const sx = i ? 1 : -1; b.position.y = brow * 0.0035; b.rotation.z = sx * brow * 0.03; });
}
function blinkAt(t, seed) { const p = (t * 0.31 + seed) % 1; return p < 0.035 ? Math.sin(p / 0.035 * Math.PI) : 0; }
function mouthAt(who, t) { const a = TL.mouth[who]; const f = t * TL.fps; const i = Math.floor(f); if (i < 0 || i >= a.length - 1) return 0; return lerp(a[i], a[i + 1], f - i); }

// poses
const P = {
  stand: (t, s = 0) => ({ spine: [0.02 * Math.sin(t * 1.1 + s), 0, 0], head: [0, 0, 0], shL: [0.04, 0, 0.1], shR: [0.04, 0, -0.1], elL: -0.2, elR: -0.2 }),
  walk: (ph) => {
    const a = Math.sin(ph), b = Math.sin(ph + Math.PI);
    return { hipY: 0.94 + Math.abs(Math.cos(ph)) * 0.025, hips: [0, 0, 0], spine: [0.04, -a * 0.06, 0],
      thL: [-a * 0.42, 0, 0], knL: Math.max(0, -Math.cos(ph)) * 0.6 + 0.05, thR: [-b * 0.42, 0, 0], knR: Math.max(0, -Math.cos(ph + Math.PI)) * 0.6 + 0.05,
      ftL: a * 0.15, ftR: b * 0.15, shL: [b * 0.32, 0, 0.1], shR: [a * 0.32, 0, -0.1], elL: -0.35, elR: -0.35 };
  },
  sit: () => ({ hipY: 0.5, thL: [-1.45, 0, 0.05], thR: [-1.45, 0, -0.05], knL: 1.3, knR: 1.3, ftL: 0.15, ftR: 0.15, spine: [-0.12, 0, 0] }),
};
const lucia = makeHuman({ skin: 0xa77a5e, jacket: 0x0d0c0f, jacketRough: 0.32, jacketMetal: 0.15, shirt: 0xf1ede6, pants: 0x1d2b44, shoes: 0xe9e6e0,
  female: true, hair: 0x1f140f, hairStyle: 'long', lips: 0x8a4a46, eyes: 0x3a220f, chestW: 0.33, earrings: true, scale: 1.0 });
const jason = makeHuman({ skin: 0xb88a6e, jacket: 0x3d4430, jacketRough: 0.7, shirt: 0x26262b, pants: 0x22252d, shoes: 0x3a2a20,
  hair: 0x17110d, hairStyle: 'short', chain: true, lips: 0x8e5a4e, eyes: 0x2a2014, chestW: 0.38, scale: 1.06 });
scene.add(lucia.root, jason.root);

// phone (handheld) with a live screen texture
const phoneTex = canvasTex(360, 760, () => {});
function drawPhone(state, t) {
  const g = phoneTex.userData.g, w = 360, h = 760;
  g.clearRect(0, 0, w, h); g.fillStyle = state === 'off' ? '#050507' : '#0b0d18'; g.fillRect(0, 0, w, h);
  if (state === 'off') { phoneTex.needsUpdate = true; return; }
  const grad = g.createLinearGradient(0, 0, 0, h); grad.addColorStop(0, '#1b1338'); grad.addColorStop(1, '#0a0b16'); g.fillStyle = grad; g.fillRect(0, 0, w, h);
  g.textAlign = 'center'; g.fillStyle = '#fff';
  if (state === 'call' || state === 'incall') {
    g.font = '600 26px Inter, sans-serif'; g.fillStyle = '#b8bad0'; g.fillText(state === 'call' ? 'incoming call…' : '00:' + String(Math.max(0, Math.floor(t))).padStart(2, '0'), w / 2, 210);
    g.font = '800 40px Inter, sans-serif'; g.fillStyle = '#fff'; g.fillText('Unknown Number', w / 2, 160);
    g.beginPath(); g.arc(w / 2, 330, 62, 0, Math.PI * 2); g.fillStyle = '#2d2f45'; g.fill(); g.font = '800 64px Inter'; g.fillStyle = '#9ea2c4'; g.fillText('?', w / 2, 352);
    if (state === 'call') {
      const pulse = 1 + 0.08 * Math.sin(t * 12);
      g.beginPath(); g.arc(95, 640, 40 * pulse, 0, Math.PI * 2); g.fillStyle = '#ff3b4e'; g.fill();
      g.beginPath(); g.arc(265, 640, 40 * pulse, 0, Math.PI * 2); g.fillStyle = '#2ed06e'; g.fill();
    } else { g.beginPath(); g.arc(w / 2, 640, 40, 0, Math.PI * 2); g.fillStyle = '#ff3b4e'; g.fill(); }
  } else if (state === 'msg' || state === 'msgshow') {
    g.font = '800 92px Inter'; g.fillStyle = '#fff'; g.fillText('1:12', w / 2, 170); g.font = '600 22px Inter'; g.fillStyle = '#b8bad0'; g.fillText('Saturday', w / 2, 205);
    if (state === 'msgshow') {
      g.fillStyle = 'rgba(40,42,62,.95)'; roundRect(g, 18, 270, w - 36, 250, 26); g.fill();
      g.textAlign = 'left'; g.font = '800 22px Inter'; g.fillStyle = '#fff'; g.fillText('Unknown Number', 40, 310); g.fillStyle = '#ff3d55'; g.fillText('now', w - 80, 310);
      let fs = 26; g.font = `800 ${fs}px Inter`;
      while (g.measureText('YOU HAVE SOMETHING').width > w - 90 && fs > 14) g.font = `800 ${--fs}px Inter`;
      g.fillStyle = '#fff';
      ['YOU HAVE SOMETHING', 'THAT BELONGS', 'TO ME.'].forEach((l, i) => g.fillText(l, 40, 365 + i * 42));
    }
  }
  phoneTex.needsUpdate = true;
}
function roundRect(g, x, y, w, h, r) { g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r); g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath(); }
const phone = new THREE.Group();
{
  const body = new THREE.Mesh(new RoundedBoxGeometry(0.075, 0.155, 0.009, 3, 0.008), new THREE.MeshStandardMaterial({ color: 0x0c0c10, metalness: 0.6, roughness: 0.3 })); phone.add(body);
  const scr = new THREE.Mesh(new THREE.PlaneGeometry(0.068, 0.146), new THREE.MeshBasicMaterial({ map: phoneTex, color: new THREE.Color(0.85, 0.85, 0.85) })); scr.position.z = 0.0048; phone.add(scr);
  phone.userData.screen = scr;
}
scene.add(phone);
let phoneState = '';
function setPhone(state, t) { if (state !== phoneState || state === 'call' || state === 'incall') { drawPhone(state, t); phoneState = state; } }

// ---------------------------------------------------------------- cars
function carBody(mat, len, wid, hgt, cabinH, sporty) {
  const g = new THREE.Group();
  const shape = new THREE.Shape();
  const L = len / 2;
  if (sporty) { shape.moveTo(-L, 0.25); shape.lineTo(-L, 0.75); shape.quadraticCurveTo(-L + 0.4, 0.9, -L + 1.0, 0.92); shape.lineTo(L - 0.8, 0.85); shape.quadraticCurveTo(L, 0.75, L, 0.45); shape.lineTo(L - 0.1, 0.25); shape.closePath(); }
  else { shape.moveTo(-L, 0.35); shape.lineTo(-L, 1.25); shape.lineTo(L - 0.5, 1.25); shape.quadraticCurveTo(L, 1.2, L, 0.9); shape.lineTo(L, 0.35); shape.closePath(); }
  const body = new THREE.Mesh(new THREE.ExtrudeGeometry(shape, { depth: wid, bevelEnabled: true, bevelSize: 0.08, bevelThickness: 0.08, bevelSegments: 3 }), mat);
  body.rotation.y = -Math.PI / 2; body.position.x = -wid / 2; g.add(body);
  const cab = new THREE.Shape();
  if (sporty) { cab.moveTo(-0.9, 0); cab.quadraticCurveTo(-0.6, cabinH, 0.1, cabinH); cab.lineTo(0.5, cabinH); cab.quadraticCurveTo(1.2, cabinH * 0.8, 1.5, 0); cab.closePath(); }
  else { cab.moveTo(-L + 0.2, 0); cab.lineTo(-L + 0.25, cabinH); cab.lineTo(L - 1.2, cabinH); cab.lineTo(L - 0.7, 0); cab.closePath(); }
  const cabin = new THREE.Mesh(new THREE.ExtrudeGeometry(cab, { depth: wid - 0.25, bevelEnabled: true, bevelSize: 0.05, bevelThickness: 0.05, bevelSegments: 2 }), M.tint);
  cabin.rotation.y = -Math.PI / 2; cabin.position.set(-(wid - 0.25) / 2, sporty ? 0.9 : 1.25, 0); g.add(cabin); g.userData.cabin = cabin;
  for (const [x, z] of [[-wid / 2 - 0.02, L - (sporty ? 0.9 : 0.9)], [wid / 2 + 0.02, L - 0.9], [-wid / 2 - 0.02, -L + 0.9], [wid / 2 + 0.02, -L + 0.9]]) {
    const w = new THREE.Group(); w.position.set(x, 0.36, z); g.add(w);
    const tire = new THREE.Mesh(new THREE.CylinderGeometry(0.36, 0.36, 0.26, 24), M.tire); tire.rotation.z = Math.PI / 2; w.add(tire);
    const rim = new THREE.Mesh(new THREE.CylinderGeometry(0.24, 0.24, 0.27, 12), M.rim); rim.rotation.z = Math.PI / 2; w.add(rim);
    g.userData.wheels = (g.userData.wheels || []).concat(w);
  }
  const hl = new THREE.Mesh(new THREE.BoxGeometry(wid * 0.8, sporty ? 0.06 : 0.12, 0.05), M.head); hl.position.set(0, sporty ? 0.68 : 1.0, L + 0.06); g.add(hl);
  const tl = new THREE.Mesh(new THREE.BoxGeometry(wid * 0.9, 0.07, 0.05), M.tail); tl.position.set(0, sporty ? 0.74 : 1.05, -L - 0.06); g.add(tl);
  g.userData.headlight = hl; g.userData.tail = tl;
  return g;
}
const car = carBody(M.paintBlack, 4.6, 1.95, 1, 0.42, true);
const suv = carBody(M.paintSUV, 5.1, 2.1, 1.6, 0.75, false);
scene.add(car, suv);
// beams (cones of light in front of each vehicle)
function beam(len, rad, col, op) { const m = new THREE.Mesh(new THREE.ConeGeometry(rad, len, 24, 1, true), new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: op, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide })); m.rotation.x = -Math.PI / 2; m.position.z = len / 2; return m; }
// (volumetric beam cones read as grey shapes in this style, so headlights rely on glow + a spotlight instead)
const suvLight = new THREE.SpotLight(0xe8eeff, 25, 60, 0.5, 0.5, 1.4); suvLight.position.set(0, 1.0, 2.6); suv.add(suvLight); suvLight.target.position.set(0, 0, 30); suv.add(suvLight.target);
// car interior (parented to car so it moves with it)
const interior = new THREE.Group(); car.add(interior);
{
  const dash = new THREE.Mesh(new RoundedBoxGeometry(1.8, 0.28, 0.5, 3, 0.08), M.interior); dash.position.set(0, 0.95, 0.95); interior.add(dash);
  const glow = new THREE.Mesh(new THREE.PlaneGeometry(0.42, 0.07), M.dashGlow); glow.position.set(0.42, 1.03, 0.69); glow.rotation.x = -0.6; interior.add(glow);
  const screen = new THREE.Mesh(new THREE.PlaneGeometry(0.22, 0.13), new THREE.MeshBasicMaterial({ color: new THREE.Color(0.6, 0.35, 1.4) })); screen.position.set(0, 1.02, 0.7); screen.rotation.x = -0.7; interior.add(screen);
  const wheel = new THREE.Mesh(new THREE.TorusGeometry(0.17, 0.022, 10, 32), M.interior); wheel.position.set(0.42, 1.0, 0.62); wheel.rotation.x = -0.35; interior.add(wheel);
  for (const x of [0.42, -0.42]) {
    const seat = new THREE.Mesh(new RoundedBoxGeometry(0.55, 0.16, 0.55, 3, 0.06), M.leatherSeat); seat.position.set(x, 0.42, -0.05); interior.add(seat);
    const back = new THREE.Mesh(new RoundedBoxGeometry(0.55, 0.75, 0.16, 3, 0.06), M.leatherSeat); back.position.set(x, 0.82, -0.36); back.rotation.x = -0.18; interior.add(back);
  }
  const mirror = new THREE.Mesh(new RoundedBoxGeometry(0.26, 0.07, 0.02, 2, 0.01), M.interior); mirror.position.set(0, 1.33, 0.82); interior.add(mirror);
  interior.userData.mirrorTex = canvasTex(256, 64, () => {});
  const mg = new THREE.Mesh(new THREE.PlaneGeometry(0.24, 0.055), new THREE.MeshBasicMaterial({ map: interior.userData.mirrorTex, color: new THREE.Color(1.6, 1.6, 1.6) })); mg.position.set(0, 1.33, 0.808); mg.rotation.y = Math.PI; interior.add(mg);
  interior.userData.mirror = mg;
  const roof = new THREE.Mesh(new THREE.BoxGeometry(1.8, 0.04, 1.6), M.interior); roof.position.set(0, 1.36, -0.1); interior.add(roof);
  const dl = new THREE.PointLight(0x7aa8ff, 1.2, 2.5); dl.position.set(0, 1.1, 0.6); interior.add(dl);
}
function drawMirror(intensity, t) {
  const tex = interior.userData.mirrorTex, g = tex.userData.g;
  g.fillStyle = '#05060c'; g.fillRect(0, 0, 256, 64);
  g.fillStyle = '#141428'; g.fillRect(0, 34, 256, 30);
  if (intensity > 0) for (const x of [108, 148]) { const gr = g.createRadialGradient(x, 30, 0, x, 30, 10 + 30 * intensity); gr.addColorStop(0, 'rgba(255,255,255,1)'); gr.addColorStop(0.3, `rgba(220,230,255,${0.9 * intensity})`); gr.addColorStop(1, 'rgba(120,140,255,0)'); g.fillStyle = gr; g.fillRect(0, 0, 256, 64); }
  tex.needsUpdate = true;
}
// duffel bag with cash + a burner phone
const bag = new THREE.Group();
{
  const b = new THREE.Mesh(new RoundedBoxGeometry(0.5, 0.24, 0.26, 4, 0.1), new THREE.MeshStandardMaterial({ color: 0x0e0e12, roughness: 0.55 })); b.position.y = 0.12; bag.add(b);
  const flapL = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.02, 0.14), new THREE.MeshStandardMaterial({ color: 0x15151b, roughness: 0.6 })); flapL.position.set(0, 0.245, -0.065); bag.add(flapL);
  const flapR = flapL.clone(); flapR.position.z = 0.065; bag.add(flapR); bag.userData.flaps = [flapL, flapR];
  const cash = new THREE.Group(); cash.position.y = 0.2; bag.add(cash); bag.userData.cash = cash;
  const cm = new THREE.MeshStandardMaterial({ map: cashTex, roughness: 0.8 }), band = new THREE.MeshStandardMaterial({ color: 0xc9a04a, roughness: 0.5 });
  for (let i = 0; i < 9; i++) { const s = new THREE.Mesh(new THREE.BoxGeometry(0.15, 0.05, 0.07), cm); s.position.set(-0.17 + (i % 3) * 0.16, 0.0 + Math.floor(i / 3) * 0.0, -0.075 + Math.floor(i / 3) * 0.075); s.rotation.y = (i % 2) * 0.12; cash.add(s); const bd = new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.052, 0.072), band); bd.position.copy(s.position); bd.rotation.copy(s.rotation); cash.add(bd); }
  const bp = new THREE.Mesh(new RoundedBoxGeometry(0.07, 0.012, 0.14, 2, 0.005), new THREE.MeshStandardMaterial({ color: 0x1b1b22, metalness: 0.5, roughness: 0.3 })); bp.position.set(0.05, 0.035, 0.0); bp.rotation.y = 0.4; cash.add(bp);
  bag.userData.burner = bp;
  const strap = new THREE.Mesh(new THREE.TorusGeometry(0.16, 0.012, 6, 24, Math.PI), new THREE.MeshStandardMaterial({ color: 0x0e0e12 })); strap.position.set(0, 0.24, 0); strap.rotation.y = Math.PI / 2; bag.add(strap);
}
interior.add(bag);

// ---------------------------------------------------------------- drive set (night boulevard that streams past the car)
const DRIVE = new THREE.Group(); DRIVE.position.set(0, 0, 6000); scene.add(DRIVE);
const TILE = 120, NT = 7;
const driveTiles = [];
{
  const r = rng(99);
  const words = ['MOTEL', 'OPEN 24H', 'TACOS', 'PAWN', 'CLUB', 'HOTEL', 'BAR', 'PALMS', 'DINER', 'CASH'];
  const cols = ['#ff3d7f', '#22e1ff', '#ffb347', '#b46bff', '#3dff9e'];
  for (let k = 0; k < NT; k++) {
    const tile = new THREE.Group(); DRIVE.add(tile); driveTiles.push(tile);
    const road = new THREE.Mesh(new THREE.PlaneGeometry(22, TILE), M.road); road.rotation.x = -Math.PI / 2; tile.add(road);
    for (let d = 0; d < 6; d++) { const ln = new THREE.Mesh(new THREE.PlaneGeometry(0.18, 4), M.line); ln.rotation.x = -Math.PI / 2; ln.position.set(0, 0.02, -TILE / 2 + d * 20 + 4); tile.add(ln); }
    for (const sx of [-1, 1]) {
      const sw = new THREE.Mesh(new THREE.BoxGeometry(6, 0.2, TILE), M.sidewalk); sw.position.set(sx * 14, 0.1, 0); tile.add(sw);
      for (let b = 0; b < 3; b++) {
        const h = 12 + r() * 30, wdt = 26 + r() * 10;
        const g = new THREE.BoxGeometry(14, h, wdt);
        g.attributes.uv.array.forEach((v, i, a) => { a[i] = v * (i % 2 ? h / 32 : wdt / 24); });
        const cc = new THREE.Color().setHSL(0.62 + r() * 0.25, 0.3, 0.35 + r() * 0.2), cl = [];
        for (let i = 0; i < g.attributes.position.count; i++) cl.push(cc.r, cc.g, cc.b);
        g.setAttribute('color', new THREE.Float32BufferAttribute(cl, 3));
        const m = new THREE.Mesh(g, M.building); m.position.set(sx * 25, h / 2, -TILE / 2 + 20 + b * 40); tile.add(m);
        if (r() > 0.35) {
          const col = cols[Math.floor(r() * cols.length)];
          const s = new THREE.Mesh(new THREE.PlaneGeometry(10, 2.5), new THREE.MeshBasicMaterial({ map: signTex(words[Math.floor(r() * words.length)], col), transparent: true, color: new THREE.Color(2.4, 2.4, 2.4), depthWrite: false, side: THREE.DoubleSide }));
          s.position.set(sx * 17.9, 5 + r() * 4, -TILE / 2 + 20 + b * 40); s.rotation.y = -sx * Math.PI / 2; tile.add(s);
          const strip = new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.2, wdt * 0.9), new THREE.MeshBasicMaterial({ color: new THREE.Color(col).multiplyScalar(2.5) })); strip.position.set(sx * 17.95, 3.2, -TILE / 2 + 20 + b * 40); tile.add(strip);
        }
      }
      for (let p = 0; p < 2; p++) {
        const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.16, 8, 6), M.pole); pole.position.set(sx * 11.5, 4, -TILE / 2 + 30 + p * 60); tile.add(pole);
        const arm = new THREE.Mesh(new THREE.BoxGeometry(2.5, 0.12, 0.12), M.pole); arm.position.set(sx * 10.3, 8, -TILE / 2 + 30 + p * 60); tile.add(arm);
        const bulb = new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.12, 0.35), M.lamp); bulb.position.set(sx * 9.3, 7.9, -TILE / 2 + 30 + p * 60); tile.add(bulb);
      }
    }
  }
}
const drivePalms = palms(Array.from({ length: 28 }, (_, i) => ({ x: (i % 2 ? 1 : -1) * 13.5, z: Math.floor(i / 2) * (TILE * NT / 14), r: i * 2.3, s: 1.1 + (i % 3) * 0.1 })));
DRIVE.add(drivePalms);
// oncoming traffic in the drive set
const oncoming = Array.from({ length: 6 }, (_, i) => { const c = carBody(new THREE.MeshPhysicalMaterial({ color: [0x2b2f45, 0x5a1020, 0x15334a, 0x3a3a3a, 0x2a2a2a, 0x40306a][i], metalness: 0.7, roughness: 0.3, clearcoat: 1 }), 4.4, 1.9, 1, 0.45, i % 2 === 0); DRIVE.add(c); return c; });
// light sweep inside the car
const sweepA = new THREE.PointLight(0xffd6a0, 0, 9, 1.4); DRIVE.add(sweepA);
const roadFill = new THREE.PointLight(0xffc890, 40, 26, 1.3); roadFill.position.set(-3, 7, 0); DRIVE.add(roadFill);
const roadFill2 = new THREE.PointLight(0x9fb4ff, 30, 30, 1.3); roadFill2.position.set(2, 6, 204); DRIVE.add(roadFill2);
const sweepB = new THREE.PointLight(0xff3d9a, 0, 10, 1.4); DRIVE.add(sweepB);
const sweepC = new THREE.PointLight(0x22d6ff, 0, 10, 1.4); DRIVE.add(sweepC);

// distance travelled by the hero car in the drive set (integral of its speed)
function speedAt(t) { if (E2) return t < 12.9 ? 32 : lerp(32, 0, ease(prog(t, 12.9, 15.8))); if (t < 44.6) return 0; if (t < 47) return lerp(0, 24, ease(prog(t, 44.6, 47))); if (t < 83.5) return 24; return lerp(24, 36, ease(prog(t, 83.5, 86))); }
const DIST = (() => { const a = new Float32Array(DUR * 60 + 2); for (let i = 1; i < a.length; i++) a[i] = a[i - 1] + speedAt(i / 60) / 60; return a; })();
const distAt = t => { const f = clamp(t, 0, DUR) * 60, i = Math.floor(f); return lerp(DIST[i], DIST[Math.min(i + 1, DIST.length - 1)], f - i); };
function updateDrive(t) {
  const d = distAt(t);
  const span = TILE * NT;
  driveTiles.forEach((tile, k) => { tile.position.z = ((k * TILE + d) % span + span) % span - span + TILE * 1.5; });
  updatePalms(drivePalms, t, d, span);
  oncoming.forEach((c, i) => { const z = ((i * 160 + d + t * 22) % 960 + 960) % 960 - 760; c.position.set(-4.2 + (i % 2) * -2.6, 0, z); c.rotation.y = 0; });
  // interior light sweeps from passing lamps and neon
  const lampPhase = ((d % 60) + 60) % 60;
  sweepA.position.set(-4, 4, -lampPhase + 30); sweepA.intensity = 22 * Math.exp(-((lampPhase - 30) ** 2) / 50);
  const np = ((d * 0.8) % 40 + 40) % 40;
  sweepB.position.set(6, 2.5, -np + 20); sweepB.intensity = 14 * Math.exp(-((np - 20) ** 2) / 30);
  const np2 = ((d * 0.65 + 17) % 52 + 52) % 52;
  sweepC.position.set(-6, 2.5, -np2 + 26); sweepC.intensity = 12 * Math.exp(-((np2 - 26) ** 2) / 30);
}

// ================================================================ EPISODE 2 sets (all procedural, original)
// overpass hiding spot (drive set, around the car's parking place)
const overpass = new THREE.Group(); DRIVE.add(overpass);
{
  const conc = new THREE.MeshStandardMaterial({ color: 0x4a4752, roughness: 0.9 });
  const deck = new THREE.Mesh(new THREE.BoxGeometry(46, 1.4, 16), conc); deck.position.set(2, 7.2, 0); overpass.add(deck);
  const lip = new THREE.Mesh(new THREE.BoxGeometry(46, 0.25, 0.3), new THREE.MeshBasicMaterial({ color: new THREE.Color(2.2, 1.4, 0.6) })); lip.position.set(2, 6.45, 8.1); overpass.add(lip);
  for (const x of [-11, 3.4, 12.6]) for (const z of [-6, 6]) { const p = new THREE.Mesh(new THREE.CylinderGeometry(0.85, 0.95, 7, 18), conc); p.position.set(x, 3.5, z); overpass.add(p); }
  const sodium = new THREE.PointLight(0xff9a40, 3, 14, 1.4); sodium.position.set(8, 6, 3); overpass.add(sodium);
  const bulb = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.15, 0.3), new THREE.MeshBasicMaterial({ color: new THREE.Color(3, 1.8, 0.7) })); bulb.position.set(8, 6.4, 3); overpass.add(bulb);
}
// construction-zone cones + barrier (drive set)
const cones = [];
const conesG = new THREE.Group(); DRIVE.add(conesG);
{
  const cm = new THREE.MeshStandardMaterial({ color: 0xff5a14, roughness: 0.5, emissive: 0x3a0e00 }), wm = new THREE.MeshStandardMaterial({ color: 0xf2f2f2, roughness: 0.4 });
  for (let i = 0; i < 9; i++) {
    const c = new THREE.Group();
    const body = new THREE.Mesh(new THREE.ConeGeometry(0.22, 0.75, 16), cm); body.position.y = 0.4; c.add(body);
    const band = new THREE.Mesh(new THREE.CylinderGeometry(0.135, 0.165, 0.1, 16), wm); band.position.y = 0.45; c.add(band);
    const base = new THREE.Mesh(new THREE.BoxGeometry(0.45, 0.05, 0.45), cm); base.position.y = 0.025; c.add(base);
    conesG.add(c); cones.push({ c, z0: -22 - i * 3.2, x: 3.6 + (i % 2) * 0.25 });
  }
  const bar = new THREE.Mesh(new THREE.BoxGeometry(2.6, 0.5, 0.12), new THREE.MeshStandardMaterial({ map: canvasTex(256, 48, (g) => { for (let i = 0; i < 8; i++) { g.fillStyle = i % 2 ? '#fff' : '#ff3d14'; g.beginPath(); g.moveTo(i * 36 - 20, 48); g.lineTo(i * 36 + 16, 0); g.lineTo(i * 36 + 52, 0); g.lineTo(i * 36 + 16, 48); g.fill(); } }), roughness: 0.5 }));
  bar.position.y = 0.9; const barG = new THREE.Group(); barG.add(bar); conesG.add(barG); cones.push({ c: barG, z0: -44, x: 6.2, bar: true });
}
// USB drive with a red tag, at the bottom of the bag
const usb = new THREE.Group();
{
  const b = new THREE.Mesh(new RoundedBoxGeometry(0.058, 0.012, 0.022, 2, 0.004), new THREE.MeshStandardMaterial({ color: 0x111116, metalness: 0.6, roughness: 0.3 })); usb.add(b);
  const k = new THREE.Mesh(new THREE.BoxGeometry(0.013, 0.005, 0.012), new THREE.MeshStandardMaterial({ color: 0xc8c8d0, metalness: 1, roughness: 0.2 })); k.position.x = 0.035; usb.add(k);
  const tag = new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.002, 0.02), new THREE.MeshStandardMaterial({ color: 0xd0141e, roughness: 0.6, emissive: 0x300000 })); tag.position.set(-0.048, 0, 0.004); tag.rotation.y = 0.3; usb.add(tag);
  usb.position.set(0.02, 0.07, 0.01); bag.add(usb); usb.visible = false;
}
// the marina at midnight (city coast)
const MAR = v3(258, 0, 300);
const marina = new THREE.Group(); scene.add(marina);
const marinaLights = [];
{
  const wood = new THREE.MeshStandardMaterial({ map: canvasTex(256, 256, (g) => { g.fillStyle = '#3b2c22'; g.fillRect(0, 0, 256, 256); for (let i = 0; i < 16; i++) { g.fillStyle = i % 2 ? '#43322a' : '#35281f'; g.fillRect(0, i * 16, 256, 14); g.fillStyle = '#1c140f'; g.fillRect(0, i * 16 + 14, 256, 2); } }), roughness: 0.85 });
  wood.map.wrapS = wood.map.wrapT = THREE.RepeatWrapping; wood.map.repeat.set(1, 10);
  const deck = new THREE.Mesh(new THREE.BoxGeometry(80, 0.35, 8), wood); deck.material.map.repeat.set(1, 1); deck.position.set(MAR.x + 40, 1.0, MAR.z); marina.add(deck);
  const pm = new THREE.MeshStandardMaterial({ color: 0x2a221c, roughness: 0.9 });
  for (let x = 0; x <= 80; x += 6) for (const z of [-4, 4]) { const p = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 0.2, 3.2, 8), pm); p.position.set(MAR.x + x, 0.4, MAR.z + z); marina.add(p); }
  const lot = new THREE.Mesh(new THREE.PlaneGeometry(60, 36), M.road); lot.rotation.x = -Math.PI / 2; lot.position.set(MAR.x - 30, 0.06, MAR.z); marina.add(lot);
  for (let i = 0; i < 4; i++) {
    const x = MAR.x + 6 + i * 20, z = MAR.z + (i % 2 ? 3.6 : -3.6);
    const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.09, 3.6, 6), M.pole); pole.position.set(x, 3.0, z); marina.add(pole);
    const bulb = new THREE.Mesh(new THREE.SphereGeometry(0.2, 10, 8), M.lamp); bulb.position.set(x, 4.85, z); marina.add(bulb);
    if (i < 3) { const L = new THREE.PointLight(0xffb36a, 7, 16, 1.4); L.position.set(x, 4.6, z); marina.add(L); marinaLights.push(L); }
  }
  // moored boats (simple original hulls)
  const hullShape = new THREE.Shape(); hullShape.moveTo(-5, -1.3); hullShape.lineTo(3, -1.3); hullShape.quadraticCurveTo(5.5, -1.0, 6, 0); hullShape.quadraticCurveTo(5.5, 1.0, 3, 1.3); hullShape.lineTo(-5, 1.3); hullShape.closePath();
  const hullGeo = new THREE.ExtrudeGeometry(hullShape, { depth: 1.3, bevelEnabled: true, bevelSize: 0.15, bevelThickness: 0.15, bevelSegments: 2 }); hullGeo.rotateX(-Math.PI / 2);
  const white = new THREE.MeshStandardMaterial({ color: 0xd8dbe2, roughness: 0.35 }), dark = new THREE.MeshStandardMaterial({ color: 0x1b2230, roughness: 0.3, metalness: 0.4 });
  marina.userData.boats = [];
  [[14, -9, 0], [34, 9.5, 1], [52, -9.5, 2], [70, 9, 0]].forEach(([x, z, k]) => {
    const b = new THREE.Group(); b.position.set(MAR.x + x, -0.4, MAR.z + z); b.rotation.y = z > 0 ? Math.PI : 0;
    const hull = new THREE.Mesh(hullGeo, white); b.add(hull);
    const cab = new THREE.Mesh(new RoundedBoxGeometry(4, 1.2, 2.1, 2, 0.2), white); cab.position.set(-0.8, 1.9, 0); b.add(cab);
    const win = new THREE.Mesh(new THREE.BoxGeometry(4.05, 0.45, 2.15), dark); win.position.set(-0.8, 2.05, 0); b.add(win);
    if (k !== 2) { const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.06, 8, 6), white); mast.position.set(0.5, 5.5, 0); b.add(mast); }
    const nav = new THREE.Mesh(new THREE.SphereGeometry(0.08, 6, 6), new THREE.MeshBasicMaterial({ color: new THREE.Color(k ? 0.4 : 3, k ? 3 : 0.4, 0.4) })); nav.position.set(5.6, 1.4, 0); b.add(nav);
    marina.add(b); marina.userData.boats.push(b);
  });
}
marina.visible = false;
// the man on the pier (original character, seen mostly in silhouette)
const man = makeHuman({ skin: 0x8f6d5a, jacket: 0x0b0b0e, jacketRough: 0.4, shirt: 0x15151a, pants: 0x0b0b0e, shoes: 0x060606,
  hair: 0x0c0a09, hairStyle: 'short', lips: 0x6e4a40, eyes: 0x1a120c, chestW: 0.4, scale: 1.08 });
scene.add(man.root); man.root.visible = false;

// ---------------------------------------------------------------- post
const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
const bloom = new UnrealBloomPass(new THREE.Vector2(W * QUALITY / 2, H * QUALITY / 2), 0.6, 0.5, 0.86); composer.addPass(bloom);
const grade = new ShaderPass({
  uniforms: { tDiffuse: { value: null }, time: { value: 0 }, fade: { value: 0 }, blur: { value: 0 }, flash: { value: 0 }, vignette: { value: 1.0 }, res: { value: new THREE.Vector2(W, H) } },
  vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.); }',
  fragmentShader: `uniform sampler2D tDiffuse; uniform float time, fade, blur, flash, vignette; uniform vec2 res; varying vec2 vUv;
    float h(vec2 p){ return fract(sin(dot(p, vec2(12.9898,78.233))) * 43758.5453); }
    void main(){
      vec3 c = vec3(0.);
      if (blur > 0.001) { for (int i = -6; i <= 6; i++) { c += texture2D(tDiffuse, vUv + vec2(float(i) * blur * 0.012, 0.)).rgb; } c /= 13.; }
      else { float ca = 0.0012; c = vec3(texture2D(tDiffuse, vUv + vec2(ca,0.)).r, texture2D(tDiffuse, vUv).g, texture2D(tDiffuse, vUv - vec2(ca,0.)).b); }
      float l = dot(c, vec3(.299,.587,.114));
      c = mix(c, c * vec3(0.92, 1.0, 1.08), smoothstep(0.5, 0.0, l));     // cool shadows
      c = mix(c, c * vec3(1.08, 0.98, 0.92), smoothstep(0.4, 1.0, l));    // warm highlights
      vec2 q = vUv - .5; q.x *= res.x / res.y * 1.2;
      c *= mix(1.0, smoothstep(0.95, 0.25, length(q)), vignette * 0.85);
      c += (h(vUv * res + time * 60.) - .5) * 0.035;
      c = mix(c, vec3(1.), flash);
      c *= 1. - fade;
      gl_FragColor = vec4(c, 1.);
    }`,
});
composer.addPass(grade);
composer.addPass(new OutputPass());

// ---------------------------------------------------------------- shots
// Each shot sets the world, characters and camera for local time u in [0,1].
const SHOTS = [];
function shot(t0, t1, fn, opts = {}) { SHOTS.push({ t0, t1, fn, ...opts }); }
const look = (pos, tgt, fov) => { camera.position.copy(pos); camera.lookAt(tgt); if (fov) { camera.fov = fov; camera.updateProjectionMatrix(); } };
const handheld = (t, amt = 1) => v3(noise1(t * 1.3) * 0.02 * amt, noise1(t * 1.1 + 7) * 0.015 * amt, 0);
const BALC = () => new THREE.Vector3().copy(balcony.position);

const headOf = h => { const p = new THREE.Vector3(); h.J.head.getWorldPosition(p); return p; };
// placement helpers in world space
function place(h, pos, yaw = 0) { h.root.position.copy(pos); h.root.rotation.set(0, yaw, 0); }
function talk(h, who, t, extra = {}) { setFace(h, { mouth: mouthAt(who, t), blink: blinkAt(t, who === 'lucia' ? 0.2 : 0.6), ...extra }); }
function attach(obj, parent, pos, rot) { parent.add(obj); obj.position.copy(pos); obj.rotation.set(...rot); }
const hide = (...o) => o.forEach(x => (x.visible = false));
const show = (...o) => o.forEach(x => (x.visible = true));

// --- Lucia on the balcony (shared by several shots)
function luciaBalcony(t, mode) {
  const b = BALC();
  place(lucia, v3(b.x - 3.6, b.y, b.z + 1.2), -Math.PI / 2 + 0.25);
  const base = P.stand(t, 0.3);
  if (mode === 'rail') { base.shL = [-0.55, 0, 0.25]; base.elL = -0.7; base.shR = [-0.55, 0, -0.25]; base.elR = -0.7; base.spine = [0.18, 0, 0]; base.head = [-0.05, 0, 0]; }
  if (mode && mode.cig !== undefined) {
    const u = mode.cig;   // 0 = at rest, reaching down to table, back up holding the cigarette
    const reach = Math.sin(clamp(u * 2) * Math.PI / 2) * (u < 0.5 ? 1 : 1 - (u - 0.5) * 2);
    base.shR = [lerp(0, -0.9, reach) + (u > 0.5 ? -0.6 * ease((u - 0.5) * 2) : 0), 0, -0.25]; base.elR = lerp(-0.2, -0.3, reach) + (u > 0.5 ? -1.2 * ease((u - 0.5) * 2) : 0);
    base.spine = [0.25 * reach, 0.3 * reach, 0]; base.head = [0.3 * reach, 0.2 * reach, 0];
  }
  if (mode && mode.phone !== undefined) {
    const u = mode.phone;   // raises right hand to her ear
    base.shR = [lerp(0, -1.1, u), 0, lerp(-0.1, -0.55, u)]; base.elR = lerp(-0.2, -2.3, u); base.handR = [0, lerp(0, 0.8, u), 0];
  }
  setPose(lucia, base);
}

const shot1 = (...a) => { if (!E2) shot(...a); };
// 0) AERIAL — the city that never sleeps
shot1(0, 6.6, (t, u) => {
  const p = V(v3(-420, 300, 420), v3(30, 120, 120), ease(u));
  const tgt = V(v3(0, 40, -40), v3(HERO.x, BALC_Y, HERO.z), ease(u));
  look(p, tgt, lerp(55, 42, u));
  luciaBalcony(t, 'rail');
  setFace(lucia, { blink: blinkAt(t, 0.2) });
});
// 1) Balcony, over the shoulder, city below
shot1(6.6, 9.6, (t, u) => {
  const b = BALC();
  luciaBalcony(t, 'rail');
  setFace(lucia, { blink: blinkAt(t, 0.2), brow: -0.3 });
  const hd = headOf(lucia), yaw = lucia.root.rotation.y, dir = v3(Math.sin(yaw), 0, Math.cos(yaw)), perp = v3(dir.z, 0, -dir.x);
  const cam = hd.clone().addScaledVector(dir, -lerp(1.35, 1.0, ease(u))).addScaledVector(perp, 0.32).add(v3(0, 0.1, 0));
  look(cam.add(handheld(t)), hd.clone().addScaledVector(dir, 40).addScaledVector(perp, -6).add(v3(0, -11, 0)), 46);
}, { tin: 'whip' });
// 2) Lucia front, takes a cigarette but doesn't light it
shot1(9.6, 12.1, (t, u) => {
  const b = BALC();
  const cu = prog(t, 9.9, 11.4);
  luciaBalcony(t, { cig: cu });
  if (cu > 0.5) { attach(cig, lucia.J.handR, v3(0, -0.06, 0.04), [0, 0, Math.PI / 2]); show(cig); } else hide(cig);
  setFace(lucia, { blink: blinkAt(t, 0.2), brow: -0.4, look: [0.3, -0.2] });
  const head = new THREE.Vector3(); lucia.J.head.getWorldPosition(head);
  look(v3(b.x - 5.1, b.y + 1.65, b.z + 1.0).add(handheld(t)), head.clone().add(v3(0, -0.08, 0)), lerp(30, 26, u));
}, { tin: 'cut' });
// 3) The phone on the table lights up
shot1(12.1, 14.6, (t, u) => {
  const b = BALC(); const tb = balcony.userData.table;
  luciaBalcony(t, { cig: 1 });
  const tw = new THREE.Vector3(); tb.getWorldPosition(tw);
  const pick = prog(t, 13.9, 14.5);
  const buzz = t < 13.9 ? Math.sin(t * 90) * 0.003 * (Math.sin(t * 6) > 0 ? 1 : 0) : 0;
  scene.add(phone); phone.position.set(tw.x - 0.1 + buzz, tw.y + 0.75 + pick * 0.3, tw.z + 0.12); phone.rotation.set(-Math.PI / 2 + pick * 1.2, 0, 0.3);
  setPhone('call', t);
  look(v3(tw.x - 0.25, tw.y + 1.05, tw.z + 0.45), v3(tw.x - 0.1, tw.y + 0.75, tw.z + 0.12), 30);
}, { tin: 'cut' });
// 4) On the call
shot1(14.6, 19.3, (t, u) => {
  const b = BALC();
  luciaBalcony(t, { phone: ease(prog(t, 14.6, 15.1)) });
  attach(phone, lucia.J.handR, v3(0.0, -0.08, 0.03), [0.1, Math.PI / 2, 0]); setPhone('incall', t - 14.6);
  hide(cig);
  talk(lucia, 'lucia', t, { brow: -0.35, look: [0.4, 0] });
  const head = new THREE.Vector3(); lucia.J.head.getWorldPosition(head);
  look(v3(b.x - 5.2, b.y + 1.62, b.z + 2.6 - u * 0.3).add(handheld(t)), head.clone().add(v3(0, -0.04, 0)), 28);
}, { tin: 'cut' });
shot1(19.3, 23.5, (t, u) => {
  const b = BALC();
  luciaBalcony(t, { phone: 1 });
  attach(phone, lucia.J.handR, v3(0.0, -0.08, 0.03), [0.1, Math.PI / 2, 0]); setPhone('incall', t - 14.6);
  const lookDown = ease(prog(t, 22.6, 23.4));
  lucia.J.head.rotation.x = lookDown * 0.45; lucia.J.head.rotation.y = -lookDown * 0.2;
  talk(lucia, 'lucia', t, { brow: -0.5, look: [0.2, -lookDown] });
  const head = new THREE.Vector3(); lucia.J.head.getWorldPosition(head);
  look(v3(b.x - 3.4 + u * 0.15, b.y + 1.6, b.z - 0.9).add(handheld(t)), head.clone().add(v3(0, -0.02, 0)), 24);
}, { tin: 'cut' });
// 5) POV: down to the street
shot1(23.5, 24.4, (t, u) => {
  const b = BALC();
  luciaBalcony(t, { phone: 1 });
  look(v3(b.x - 4.4, b.y + 1.6, b.z + 1.2), v3(b.x - 30, 0, b.z + 8 - u * 6), lerp(38, 30, u));
}, { tin: 'cut' });
// 6) "Then I guess you should come find me." — hangs up
shot1(24.4, 27.8, (t, u) => {
  const b = BALC();
  const down = ease(prog(t, 26.5, 27.3));
  luciaBalcony(t, { phone: 1 - down });
  if (down < 0.6) { attach(phone, lucia.J.handR, v3(0.0, -0.08, 0.03), [0.1, Math.PI / 2, 0]); setPhone('incall', t - 14.6); } else setPhone('off', t);
  talk(lucia, 'lucia', t, { brow: -0.3, smirk: ease(prog(t, 26.2, 27)), look: [0.5, -0.1] });
  const head = new THREE.Vector3(); lucia.J.head.getWorldPosition(head);
  look(v3(b.x - 4.7, b.y + 1.62, b.z + 1.6).add(handheld(t)), head.clone().add(v3(0, -0.03, 0)), lerp(26, 21, u));
}, { tin: 'cut' });

// --- street: the car arrives
const CURB = () => v3(HERO.x - 10, 0, HERO.z);
function carArrive(t) {
  const c = CURB();
  const u = ease(prog(t, 27.8, 31.2));
  const z = lerp(c.z + 120, c.z + 4, u);
  car.position.set(c.x - 1.6, 0, z); car.rotation.set(0, Math.PI, 0);
  car.userData.wheels.forEach(w => (w.rotation.x = -z * 1.4));
}
shot1(27.8, 31.6, (t, u) => {
  hide(lucia.root); show(jason.root);
  carArrive(t);
  placeInCar(t);
  const c = CURB();
  look(v3(c.x - 6.5, 0.7, c.z - 6 + u * 2).add(handheld(t, 0.6)), v3(car.position.x, 0.9, car.position.z), lerp(34, 30, u));
}, { tin: 'whip', world: 'city' });
// Lucia walks out to the car and gets in
shot1(31.6, 35.4, (t, u) => {
  show(lucia.root);
  const c = CURB();
  car.position.set(c.x - 1.6, 0, c.z + 4); car.rotation.set(0, Math.PI, 0);
  placeInCar(t, { jasonOnly: true });
  const walk = prog(t, 31.7, 34.3);
  const start = v3(HERO.x - 1.5, 0.2, HERO.z - 1.5), door = v3(c.x - 0.1, 0.1, c.z + 4.5);
  const pos = V(start, door, walk);
  place(lucia, pos, Math.atan2(door.x - start.x, door.z - start.z));
  if (walk < 1) setPose(lucia, P.walk(walk * 16)); else {
    const g = ease(prog(t, 34.4, 35.2)); const p = P.stand(t); p.shL = [-0.9 * (1 - g), 0, 0.3]; p.elL = -0.5; setPose(lucia, p);
    lucia.root.position.y = 0.1 - g * 0.3; lucia.root.position.x -= g * 0.6;
  }
  setFace(lucia, { blink: blinkAt(t, 0.2), brow: -0.3 });
  const door2 = car.userData.door; if (door2) door2.rotation.y = 0;
  const lp = lucia.root.position;
  look(v3(lp.x - 5 + walk * 1.2, 1.4, lp.z - 4.5).add(handheld(t, 0.6)), v3(lp.x, 1.3, lp.z), 34);
}, { tin: 'cut', world: 'city' });

// --- inside the car (drive set). Car sits at the drive-set origin, the city streams past.
function placeInCar(t, opts = {}) {
  // seats are in car-local coords: driver at x=+0.42 (left-hand drive seen from the front), passenger at -0.42
  const wp = new THREE.Vector3(), q = car.quaternion.clone();
  const driver = v3(0.42, 0.0, -0.05).applyQuaternion(q).add(car.position);
  place(jason, driver, car.rotation.y);
  const pj = P.sit(); pj.shL = [-1.1, 0, 0.12]; pj.elL = -0.55; pj.shR = [-1.1, 0, -0.12]; pj.elR = -0.55; pj.hipY = 0.45; setPose(jason, pj);
  if (!opts.jasonOnly) {
    const pass = v3(-0.42, 0.0, -0.05).applyQuaternion(q).add(car.position);
    place(lucia, pass, car.rotation.y);
    const pl = P.sit(); pl.hipY = 0.45; pl.shL = [-0.55, 0, 0.1]; pl.elL = -0.9; pl.shR = [-0.55, 0, -0.1]; pl.elR = -0.9; setPose(lucia, pl);
  }
}
const carLat = t => E2 ? 6.6 * ease(prog(t, 12.9, 14.9)) : 0;
const carYaw = t => E2 ? Math.PI - 0.42 * Math.sin(Math.PI * prog(t, 12.9, 15.1)) : Math.PI;
function inCar(t, inside = true) {
  show(lucia.root, jason.root, car, interior);
  car.userData.cabin.visible = !inside; car.userData.tail.visible = !inside;
  car.position.set(DRIVE.position.x + carLat(t), 0, DRIVE.position.z); car.rotation.set(0, carYaw(t), 0);
  updateDrive(t); interior.add(bag);
  car.userData.wheels.forEach(w => (w.rotation.x = distAt(t) * 2.8));
  placeInCar(t);
  bag.position.set(-0.42, 0.62, 0.2); bag.rotation.set(0, 0.2, 0);
}
const carPt = (x, y, z) => v3(x, y, z).applyQuaternion(car.quaternion).add(car.position);
shot1(35.4, 38.7, (t, u) => {        // two-shot through the windscreen
  inCar(t);
  jason.J.head.rotation.y = -0.45 * ease(prog(t, 35.5, 36.0));
  talk(jason, 'jason', t, { brow: 0.4, look: [-0.6, 0] }); talk(lucia, 'lucia', t, { brow: -0.3, look: [-0.3, 0] });
  look(carPt(0, 1.26, 1.45).add(handheld(t, 0.4)), carPt(0, 1.12, -0.2), lerp(74, 68, u));
}, { tin: 'dip', world: 'drive' });
shot1(38.7, 41.2, (t, u) => {        // Lucia, over Jason's shoulder
  inCar(t);
  lucia.J.head.rotation.y = 0.45; jason.J.head.rotation.y = -0.5;
  talk(lucia, 'lucia', t, { brow: -0.4, look: [0.5, 0] }); talk(jason, 'jason', t, {});
  look(carPt(0.62, 1.22, 0.12).add(handheld(t, 0.5)), headOf(lucia).add(v3(0, -0.03, 0)), 28);
}, { tin: 'cut', world: 'drive' });
shot1(41.2, 42.4, (t, u) => {        // Jason: "What did you do?"
  inCar(t);
  jason.J.head.rotation.y = -0.55; lucia.J.head.rotation.y = 0.4;
  talk(jason, 'jason', t, { brow: 0.6, look: [-0.5, 0] });
  look(carPt(-0.55, 1.22, 0.25).add(handheld(t, 0.5)), headOf(jason).add(v3(0, -0.03, 0)), 28);
}, { tin: 'cut', world: 'drive' });
shot1(42.4, 45.0, (t, u) => {        // Lucia looks ahead
  inCar(t);
  lucia.J.head.rotation.y = lerp(0.4, 0, ease(prog(t, 43.6, 44.4))); jason.J.head.rotation.y = -0.5;
  talk(lucia, 'lucia', t, { brow: -0.5, look: [0, 0] });
  look(carPt(-0.2, 1.25, 1.0).add(handheld(t, 0.4)), headOf(lucia).add(v3(0, -0.03, 0)), lerp(26, 23, u));
}, { tin: 'cut', world: 'drive' });
shot1(45.0, 47.3, (t, u) => {        // exterior: the car speeds away
  inCar(t, false);
  const d0 = distAt(45.0), d = distAt(t);
  look(v3(DRIVE.position.x + 4.2, 0.9, DRIVE.position.z + 4 + (d - d0)), carPt(0, 0.7, 0), lerp(42, 34, u));
}, { tin: 'whip', world: 'drive' });
shot1(47.3, 52.4, (t, u) => {        // "Lucia, what's in the bag?"
  inCar(t);
  jason.J.head.rotation.y = -0.4 * (Math.sin(t * 0.9) > -0.2 ? 1 : 0.3); lucia.J.head.rotation.y = -0.6;  // she looks out of her window
  talk(jason, 'jason', t, { brow: 0.5, look: [-0.6, 0] }); talk(lucia, 'lucia', t, { brow: -0.4, look: [-0.6, 0] });
  look(carPt(0.03, 1.26, 1.45).add(handheld(t, 0.5)), carPt(-0.02, 1.12, -0.2), lerp(72, 64, u));
}, { tin: 'cut', world: 'drive' });
shot1(52.4, 55.6, (t, u) => {        // the bag opens: cash and a phone
  inCar(t);
  lucia.J.head.rotation.x = 0.5; lucia.J.head.rotation.y = 0;
  const open = ease(prog(t, 52.7, 54.0));
  bag.userData.flaps[0].rotation.x = -open * 1.4; bag.userData.flaps[0].position.y = 0.245 + open * 0.05;
  bag.userData.flaps[1].rotation.x = open * 1.4; bag.userData.flaps[1].position.y = 0.245 + open * 0.05;
  bag.userData.cash.position.y = 0.12 + open * 0.1;
  const bp = carPt(-0.42, 0.78, 0.2);
  look(v3(bp.x, bp.y + 0.55 - u * 0.1, bp.z).add(carPt(0, 0, 0.18).sub(car.position)), bp, lerp(42, 34, u));
}, { tin: 'cut', world: 'drive' });
shot1(55.6, 57.3, (t, u) => {
  inCar(t); bag.userData.cash.position.y = 0.22;
  jason.J.head.rotation.y = -0.55;
  talk(jason, 'jason', t, { brow: 0.8, look: [-0.5, -0.2] });
  look(carPt(-0.5, 1.2, 0.3).add(handheld(t, 0.5)), headOf(jason).add(v3(0, -0.03, 0)), 27);
}, { tin: 'cut', world: 'drive' });
shot1(57.3, 61.2, (t, u) => {
  inCar(t); bag.userData.cash.position.y = 0.22;
  lucia.J.head.rotation.y = lerp(0.1, 0.45, ease(prog(t, 57.3, 58)));
  talk(lucia, 'lucia', t, { brow: -0.2, smirk: ease(prog(t, 59.8, 60.8)) * 0.8, look: [0.5, 0] });
  look(carPt(0.55, 1.22, 0.2).add(handheld(t, 0.5)), headOf(lucia).add(v3(0, -0.03, 0)), lerp(27, 23, u));
}, { tin: 'cut', world: 'drive' });
// --- SUV
function suvAt(t) {
  roadFill2.position.set(2, 6, 0);
  const gap = E2 ? (t < 12.9 ? 11 + 1.5 * Math.sin(t * 0.8) : 11 + 1.5 * Math.sin(12.9 * 0.8) - (32 * (t - 12.9) - (distAt(t) - distAt(12.9)))) : t < 61 ? 400 : t < 70 ? lerp(300, 60, ease(prog(t, 61, 70))) : lerp(60, 11, ease(prog(t, 70, 84)));
  suv.position.set(DRIVE.position.x + (E2 ? 0.5 : 1.2) * Math.sin(t * 0.7), 0, DRIVE.position.z + gap); suv.rotation.set(0, Math.PI, 0);
  suv.userData.wheels.forEach(w => (w.rotation.x = t * 30));
  roadFill2.position.set(suv.position.x - DRIVE.position.x + 2, 6, gap * 0.5 + 4);
  return gap;
}
shot1(61.2, 64.9, (t, u) => {        // through the rear window: headlights appear
  inCar(t); bag.userData.cash.position.y = 0.22; show(suv); suvAt(t);
  look(carPt(0, 1.25, 0.6), carPt(0, 1.05, -8), 32);
}, { tin: 'cut', world: 'drive' });
shot1(64.9, 68.6, (t, u) => {        // rear-view mirror + Jason
  inCar(t); show(suv); const gap = suvAt(t);
  drawMirror(clamp(1 - gap / 260) * 1.2 + 0.25, t);
  jason.J.head.rotation.x = -0.1; jason.J.head.rotation.y = -0.1;
  talk(jason, 'jason', t, { brow: 0.9, look: [-0.2, 0.5] });
  look(carPt(0.12, 1.27, 0.5).add(handheld(t, 0.4)), carPt(0.02, 1.33, 0.82), lerp(36, 30, u));
}, { tin: 'cut', world: 'drive' });
shot1(68.6, 71.2, (t, u) => {        // Lucia turns around
  inCar(t); show(suv); suvAt(t);
  const turn = ease(prog(t, 68.7, 69.8));
  lucia.J.spine.rotation.y = turn * 0.7; lucia.J.head.rotation.y = turn * 1.0; lucia.J.head.rotation.x = -0.05;
  setFace(lucia, { blink: blinkAt(t, 0.2), brow: 0.3 * turn, look: [0.6 * turn, 0] });
  look(carPt(0.05, 1.28, -0.85).add(handheld(t, 0.6)), headOf(lucia).add(v3(0, -0.02, 0)), 34);
}, { tin: 'cut', world: 'drive' });
shot1(71.2, 75.5, (t, u) => {        // exterior chase
  inCar(t); show(suv); suvAt(t);
  inCar(t, false);
  const gap = suvAt(t);
  const p = carPt(1.6 - u * 0.8, 1.9 + u * 0.3, -gap - 7.5);
  look(p.add(handheld(t, 1.4)), carPt(0, 0.9, 0), lerp(30, 26, u));
}, { tin: 'whip', world: 'drive' });
shot1(75.5, 80.6, (t, u) => {        // the message
  inCar(t); show(suv); suvAt(t);
  const pu = ease(prog(t, 75.5, 76.1));
  scene.add(phone);
  const buzz = t > 75.6 && t < 76.3 ? Math.sin(t * 80) * 0.004 : 0;
  const ph = carPt(-0.4 + buzz, 0.9 + pu * 0.06, 0.16);
  phone.position.copy(ph);
  phone.quaternion.copy(car.quaternion).multiply(new THREE.Quaternion().setFromEuler(new THREE.Euler(-2.15, 0, Math.PI + 0.05)));
  lucia.J.head.rotation.x = 0.45;
  setPhone(t < 76.3 ? 'msg' : 'msgshow', t);
  const nrm = v3(0, 0, 1).applyQuaternion(phone.quaternion);
  look(ph.clone().add(nrm.multiplyScalar(lerp(0.3, 0.24, u))).add(v3(0, 0.0, 0)), ph, 38);
}, { tin: 'cut', world: 'drive' });
shot1(80.6, 84.0, (t, u) => {        // "Keep driving."
  inCar(t); show(suv); suvAt(t);
  attach(phone, lucia.J.handR, v3(0, -0.07, 0.04), [-0.4, 0, 0]); setPhone('off', t);
  lucia.J.head.rotation.y = ease(prog(t, 80.7, 81.5)) * 0.5;
  talk(lucia, 'lucia', t, { brow: -0.6, look: [0.7, 0] });
  look(carPt(0.58, 1.22, 0.25).add(handheld(t, 0.4)), headOf(lucia).add(v3(0, -0.03, 0)), lerp(26, 20, u));
}, { tin: 'cut', world: 'drive' });
shot1(84.0, 86.6, (t, u) => {        // the car pulls away, the SUV right behind
  inCar(t); show(suv); suvAt(t);
  inCar(t, false);
  const gap = suvAt(t);
  look(carPt(-2.5, 4.5 + u * 4, -gap - 14 - u * 8), carPt(0, 0.6, 6), lerp(34, 40, u));
}, { tin: 'whip', world: 'drive' });
shot1(86.6, 90.01, () => { look(v3(0, 1, 0), v3(0, 1, -1), 40); }, { tin: 'cut', black: true });

// ================================================================ EPISODE 2 shots
const shot2 = (...a) => { if (E2) shot(...a); };
function luciaSit(u = 0, holdUp = 0, armsDown = false) {               // passenger pose; u raises the right hand to the ear, holdUp to chest height
  const pl = P.sit(); pl.hipY = 0.45; pl.shL = [-0.55, 0, 0.1]; pl.elL = -0.9;
  pl.shR = [lerp(-0.55, -1.1, u), 0, lerp(-0.1, -0.55, u)]; pl.elR = lerp(-0.9, -2.3, u); pl.handR = [0, lerp(0, 0.8, u), 0];
  pl.shL = [-0.55 - holdUp * 0.42, 0, 0.1 - holdUp * 0.32]; pl.elL = -0.9 - holdUp * 0.7; pl.handL = [0, -holdUp * 0.9, 0];
  if (armsDown) { pl.shL = [-0.15, 0, 0.32]; pl.elL = -0.25; pl.shR = [-0.15, 0, -0.32]; pl.elR = -0.25; }
  setPose(lucia, pl);
}
function dark2() { car.userData.headlight.visible = false; car.userData.tail.visible = false; roadFill.intensity = 5; overpass.visible = true; }
function suvCrawl(t) {                               // the SUV searching, slowly, on the road beside the overpass
  show(suv); const z = lerp(70, -50, prog(t, 21, 33));
  suv.position.set(DRIVE.position.x - 3, 0, DRIVE.position.z + z); suv.rotation.set(0, Math.PI, 0);
  suv.userData.wheels.forEach(w => (w.rotation.x = -z * 2.8));
  sweepA.position.set(-3, 1.2, z - 5); sweepA.color.set(0xe8eeff); sweepA.intensity = 30; sweepA.distance = 26;
  return z;
}
function updateCones(t) {
  show(conesG); const d0 = distAt(11.5), d = distAt(t), cx = carLat(t);
  for (const k of cones) {
    let z = k.z0 + (d - d0), x = k.x, y = 0, rx = 0, rz = 0;
    // contact when the cone reaches the car's nose while the car is in its lane
    let tc = -1; for (let s = 11.5; s <= t; s += 1 / 30) { if (k.z0 + (distAt(s) - d0) > -2.4 && Math.abs(carLat(s) - k.x) < 1.6) { tc = s; break; } }
    if (tc > 0) {
      const tau = t - tc, zc = k.z0 + (distAt(tc) - d0);
      x += (k.bar ? 1.5 : 2.6) * tau + (k.x - carLat(tc)) * 0.5; y = Math.max(0, 4.5 * tau - 4.9 * tau * tau) * (k.bar ? 0.6 : 1);
      z = zc - 9 * tau + (d - distAt(tc)) * 0.9; rx = tau * 9; rz = tau * 6;
    }
    k.c.position.set(x, y, z); k.c.rotation.set(rx, 0, rz);
  }
}
// cold open: the chase continues
shot2(0, 4.6, (t, u) => {
  inCar(t, false); const gap = suvAt(t);
  look(carPt(1.6 - u * 0.6, 1.9 + u * 0.4, -gap - 7.5).add(handheld(t, 1.4)), carPt(0, 0.9, 0), lerp(30, 27, u));
}, { tin: 'cut', world: 'drive' });
shot2(4.6, 8.0, (t, u) => {          // "Next exit. Take it."
  inCar(t); show(suv); suvAt(t);
  lucia.J.head.rotation.y = lerp(0.5, 0.15, ease(prog(t, 6.6, 7.4)));
  talk(lucia, 'lucia', t, { brow: -0.6, look: [0.6, 0] }); talk(jason, 'jason', t, {});
  look(carPt(0.6, 1.22, 0.18).add(handheld(t, 0.7)), headOf(lucia).add(v3(0, -0.03, 0)), 26);
}, { tin: 'cut', world: 'drive' });
shot2(8.0, 10.7, (t, u) => {         // Jason: "That's not an exit..."
  inCar(t); show(suv); suvAt(t);
  jason.J.head.rotation.y = -0.5 * (1 - ease(prog(t, 9.4, 10.0)));
  talk(jason, 'jason', t, { brow: 0.9, look: [-0.5, 0] });
  look(carPt(-0.55, 1.22, 0.25).add(handheld(t, 0.7)), headOf(jason).add(v3(0, -0.03, 0)), 27);
}, { tin: 'cut', world: 'drive' });
shot2(10.7, 12.6, (t, u) => {        // "Take it."
  inCar(t); show(suv); suvAt(t);
  lucia.J.head.rotation.y = 0.5;
  talk(lucia, 'lucia', t, { brow: -0.8, look: [0.7, 0] });
  look(carPt(0.58, 1.22, 0.24).add(handheld(t, 0.5)), headOf(lucia).add(v3(0, -0.02, 0)), lerp(22, 18, u));
}, { tin: 'cut', world: 'drive' });
shot2(12.6, 16.4, (t, u) => {        // the swerve through the construction zone; the SUV overshoots
  inCar(t, false); show(suv); suvAt(t); updateCones(t);
  look(v3(DRIVE.position.x + 13 - u * 2, 3.2 + u, DRIVE.position.z - 26).add(handheld(t, 1.2)), carPt(-1.0, 0.8, 1.5), lerp(40, 34, u));
}, { tin: 'whip', world: 'drive' });
// hiding under the overpass, lights off
shot2(16.4, 20.6, (t, u) => {
  inCar(t, false); dark2();
  look(v3(DRIVE.position.x + 7.6 - u * 0.5, 1.5, DRIVE.position.z + 14 - u * 2), carPt(0, 0.9, 0), lerp(44, 38, u));
}, { tin: 'dip', world: 'drive' });
shot2(20.6, 24.6, (t, u) => {        // they hold their breath; light sweeps across their faces
  inCar(t); dark2(); suvCrawl(t);
  const duck = ease(prog(t, 20.8, 21.6));
  lucia.J.spine.rotation.x = 0.12 * duck; jason.J.spine.rotation.x = 0.1 * duck;
  lucia.J.head.rotation.y = -0.5; jason.J.head.rotation.y = -0.4;
  talk(jason, 'jason', t, { brow: 0.8, look: [-0.7, 0] }); talk(lucia, 'lucia', t, { brow: 0.2, look: [-0.8, 0] });
  look(carPt(0.03, 1.24, 1.45).add(handheld(t, 0.3)), carPt(-0.02, 1.1, -0.2), lerp(72, 66, u));
}, { tin: 'cut', world: 'drive' });
shot2(24.6, 28.4, (t, u) => {        // "People who don't forget."
  inCar(t); dark2(); suvCrawl(t);
  lucia.J.head.rotation.y = lerp(-0.5, 0.3, ease(prog(t, 24.8, 25.6)));
  talk(lucia, 'lucia', t, { brow: -0.5, look: [lerp(-0.8, 0.5, ease(prog(t, 24.8, 25.6))), 0] });
  look(carPt(0.6, 1.22, 0.2).add(handheld(t, 0.3)), headOf(lucia).add(v3(0, -0.03, 0)), lerp(24, 20, u));
}, { tin: 'cut', world: 'drive' });
shot2(28.4, 33.0, (t, u) => {        // the SUV crawls past and moves on
  inCar(t, false); dark2(); suvCrawl(t);
  look(v3(DRIVE.position.x + 9.6, 1.05, DRIVE.position.z - 3.2), suv.position.clone().add(v3(0, 1.1, 0)), 36);
}, { tin: 'cut', world: 'drive' });
// the burner rings
shot2(33.0, 36.4, (t, u) => {        // the burner buzzes in the bag; she lifts it
  inCar(t); dark2();
  const pick = ease(prog(t, 34.4, 35.6)); luciaSit(0, pick * 0.85);
  const buzz = Math.sin(t * 90) * 0.004 * (Math.sin(t * 6) > 0 ? 1 : 0);
  if (pick > 0) { attach(phone, lucia.J.handL, v3(buzz, -0.08, 0.03), [0.6, Math.PI, 0]); }
  else { scene.add(phone); phone.position.copy(carPt(-0.42 + buzz, 0.87, 0.24)); phone.quaternion.copy(car.quaternion).multiply(new THREE.Quaternion().setFromEuler(new THREE.Euler(-Math.PI / 2, 0, 0.3))); }
  setPhone('call', t);
  lucia.J.head.rotation.x = 0.35 * (1 - pick * 0.5);
  setFace(lucia, { blink: blinkAt(t, 0.2), brow: -0.3, look: [0, -0.8] });
  look(carPt(-0.22, 1.32, 0.9).add(handheld(t, 0.3)), carPt(-0.42, 0.98, 0.18), lerp(42, 36, u));
}, { tin: 'cut', world: 'drive' });
shot2(36.4, 41.2, (t, u) => {        // "You can keep running, Lucia. But he can't."
  inCar(t); dark2(); luciaSit(ease(prog(t, 36.4, 36.9)));
  attach(phone, lucia.J.handR, v3(0.0, -0.08, 0.03), [0.1, Math.PI / 2, 0]); setPhone('incall', t - 36.4);
  setFace(lucia, { blink: blinkAt(t, 0.2), brow: -0.5, look: [0.3, 0] });
  lucia.J.head.rotation.y = lerp(0, 0.45, ease(prog(t, 39.6, 40.4)));
  look(carPt(0.6, 1.22, 0.18).add(handheld(t, 0.4)), headOf(lucia).add(v3(0, -0.03, 0)), lerp(27, 23, u));
}, { tin: 'cut', world: 'drive' });
shot2(41.2, 43.5, (t, u) => {        // Jason doesn't know what was said
  inCar(t); dark2(); luciaSit(1); attach(phone, lucia.J.handR, v3(0.0, -0.08, 0.03), [0.1, Math.PI / 2, 0]);
  jason.J.head.rotation.y = -0.55;
  setFace(jason, { blink: blinkAt(t, 0.6), brow: 0.6, look: [-0.5, 0] });
  look(carPt(-0.55, 1.22, 0.25).add(handheld(t, 0.4)), headOf(jason).add(v3(0, -0.03, 0)), 27);
}, { tin: 'cut', world: 'drive' });
shot2(43.5, 46.0, (t, u) => {        // "Leave him out of this."
  inCar(t); dark2(); luciaSit(1); attach(phone, lucia.J.handR, v3(0.0, -0.08, 0.03), [0.1, Math.PI / 2, 0]); setPhone('incall', t - 36.4);
  lucia.J.head.rotation.y = 0.1;
  talk(lucia, 'lucia', t, { brow: -0.9, look: [0.2, 0] });
  look(carPt(0.58, 1.22, 0.24).add(handheld(t, 0.4)), headOf(lucia).add(v3(0, -0.02, 0)), lerp(21, 18, u));
}, { tin: 'cut', world: 'drive' });
shot2(46.0, 52.0, (t, u) => {        // "Midnight. The old marina..." — she hangs up
  inCar(t); dark2();
  const down = ease(prog(t, 50.4, 51.2)); luciaSit(1 - down);
  if (down < 0.6) { attach(phone, lucia.J.handR, v3(0.0, -0.08, 0.03), [0.1, Math.PI / 2, 0]); setPhone('incall', t - 36.4); } else setPhone('off', t);
  lucia.J.head.rotation.y = 0;
  setFace(lucia, { blink: blinkAt(t, 0.2), brow: -0.4 - 0.3 * down, look: [0, -0.2] });
  look(carPt(-0.2, 1.25, 1.0).add(handheld(t, 0.3)), headOf(lucia).add(v3(0, -0.04, 0)), lerp(27, 22, u));
}, { tin: 'cut', world: 'drive' });
// the truth
shot2(52.0, 56.0, (t, u) => {        // "Lucia. What is really in that bag?"
  inCar(t); dark2(); luciaSit(0);
  jason.J.head.rotation.y = -0.5; lucia.J.head.rotation.y = lerp(0, 0.35, ease(prog(t, 54.6, 55.4)));
  talk(jason, 'jason', t, { brow: 0.6, look: [-0.6, 0] }); setFace(lucia, { blink: blinkAt(t, 0.2), brow: -0.3, look: [0.3, -0.3] });
  look(carPt(0.03, 1.25, 1.45).add(handheld(t, 0.4)), carPt(-0.02, 1.1, -0.2), lerp(70, 60, u));
}, { tin: 'cut', world: 'drive' });
shot2(56.0, 60.4, (t, u) => {        // from the bottom of the bag: a drive with a red tag
  inCar(t); dark2();
  const up = ease(prog(t, 56.3, 57.6)); luciaSit(0, up);
  if (up > 0.15) { attach(usb, lucia.J.handL, v3(0, -0.085, 0.03), [0, 0, Math.PI / 2]); show(usb); }
  lucia.J.head.rotation.x = 0.3; lucia.J.head.rotation.y = -0.1;
  talk(lucia, 'lucia', t, { brow: -0.5, look: [0, -0.7] });
  look(carPt(-0.2, 1.3, 0.9).add(handheld(t, 0.3)), carPt(-0.4, 1.06, 0.15), lerp(38, 32, u));
}, { tin: 'cut', world: 'drive' });
shot2(60.4, 63.4, (t, u) => {        // "Then what is it?"
  inCar(t); dark2(); luciaSit(0);
  jason.J.head.rotation.y = -0.55; jason.J.head.rotation.x = 0.15;
  talk(jason, 'jason', t, { brow: 0.7, look: [-0.5, -0.3] });
  look(carPt(-0.55, 1.22, 0.25).add(handheld(t, 0.4)), headOf(jason).add(v3(0, -0.03, 0)), 27);
}, { tin: 'cut', world: 'drive' });
shot2(63.4, 68.0, (t, u) => {        // "Every name they ever paid."
  inCar(t); dark2(); const up = ease(prog(t, 63.5, 64.4)); luciaSit(0, up);
  attach(usb, lucia.J.handL, v3(0, -0.085, 0.03), [0, 0, Math.PI / 2]); show(usb);
  lucia.J.head.rotation.y = lerp(0, 0.4, ease(prog(t, 66.0, 66.8))); lucia.J.head.rotation.x = 0.12 * (1 - ease(prog(t, 66.0, 66.8)));
  talk(lucia, 'lucia', t, { brow: -0.6, look: [0.2, -0.4 * (1 - ease(prog(t, 66.0, 66.8)))] });
  look(carPt(0.55, 1.16, 0.32).add(handheld(t, 0.3)), headOf(lucia).add(v3(0, -0.15, 0.05)), lerp(36, 31, u));
}, { tin: 'cut', world: 'drive' });
shot2(68.0, 71.0, (t, u) => {        // "Then they're never letting us go."
  inCar(t); dark2(); luciaSit(0, 1); attach(usb, lucia.J.handL, v3(0, -0.085, 0.03), [0, 0, Math.PI / 2]); show(usb);
  jason.J.head.rotation.y = -0.2; jason.J.spine.rotation.x = 0.06;
  talk(jason, 'jason', t, { brow: 0.4, look: [-0.2, 0] });
  look(carPt(-0.5, 1.21, 0.3 + u * 0.05).add(handheld(t, 0.3)), headOf(jason).add(v3(0, -0.03, 0)), lerp(26, 22, u));
}, { tin: 'cut', world: 'drive' });
// the marina, midnight
function marinaCar(t) {
  show(marina, car, interior, suv); marina.visible = true;
  const u = ease(prog(t, 71.0, 75.2)), x = lerp(MAR.x - 90, MAR.x - 9, u);
  car.position.set(x, 0, MAR.z - 1.2); car.rotation.set(0, Math.PI / 2, 0);
  car.userData.wheels.forEach(w => (w.rotation.x = x * 2.8));
  interior.add(bag); bag.position.set(-0.42, 0.62, 0.2); bag.rotation.set(0, 0.2, 0);
  placeInCar(t);
  suv.position.set(MAR.x + 72, 1.18, MAR.z); suv.rotation.set(0, -Math.PI / 2, 0);
  suvLight.intensity = 30; suvLight.distance = 140; marinaLights.forEach(L => (L.intensity = 14));
  marina.userData.boats.forEach((b, i) => { b.position.y = -0.4 + Math.sin(t * 0.9 + i * 1.7) * 0.06; b.rotation.z = Math.sin(t * 0.7 + i) * 0.015; });
  scene.fog.density = 0.011;
  man.root.visible = true; place(man, v3(MAR.x + 68.6, 1.18, MAR.z + 0.3), -Math.PI / 2); setPose(man, P.stand(t, 0.8));
  man.root.visible = t > 82.9;
}
shot2(71.0, 75.4, (t, u) => {
  marinaCar(t); car.userData.cabin.visible = true; car.userData.tail.visible = true; hide(interior);
  const p = V(v3(MAR.x - 40, 24, MAR.z - 46), v3(MAR.x - 22, 5, MAR.z - 14), ease(u));
  look(p, V(v3(MAR.x + 30, 1, MAR.z), v3(MAR.x - 2, 1.4, MAR.z), ease(u)), lerp(44, 38, u));
}, { tin: 'dip' });
shot2(75.4, 79.4, (t, u) => {        // "This is a bad idea." / "It's the only one we've got."
  marinaCar(t); car.userData.cabin.visible = false; car.userData.tail.visible = false;
  lucia.J.head.rotation.y = t < 77.4 ? 0 : 0.4; jason.J.head.rotation.y = t < 77.4 ? 0 : -0.35;
  talk(jason, 'jason', t, { brow: 0.6, look: [0, 0] }); talk(lucia, 'lucia', t, { brow: -0.4, look: [t < 77.4 ? 0 : 0.6, 0] });
  look(carPt(0.03, 1.25, 1.45).add(handheld(t, 0.3)), carPt(-0.02, 1.1, -0.2), lerp(68, 60, u));
}, { tin: 'cut' });
shot2(79.4, 83.0, (t, u) => {        // she walks down the pier into the headlights
  marinaCar(t); car.userData.cabin.visible = true; car.userData.tail.visible = true;
  const w = prog(t, 79.4, 83.0), x = lerp(MAR.x + 50, MAR.x + 55.5, w);
  place(lucia, v3(x, 1.18, MAR.z - 0.4), Math.PI / 2); setPose(lucia, P.walk(w * 10));
  attach(bag, lucia.J.handR, v3(0, -0.12, 0), [0, Math.PI / 2, 0]); bag.scale.setScalar(1);
  setFace(lucia, { blink: blinkAt(t, 0.2), brow: -0.5 });
  look(v3(x - 5.5, 1.9, MAR.z - 1.3).add(handheld(t, 0.6)), v3(x + 12, 1.4, MAR.z), 36);
}, { tin: 'cut' });
shot2(83.0, 86.6, (t, u) => {        // a man steps into the light: "Hello, Lucia."
  marinaCar(t); car.userData.cabin.visible = true;
  const x = MAR.x + 55.5;
  place(lucia, v3(x, 1.18, MAR.z - 0.4), Math.PI / 2); setPose(lucia, P.stand(t));
  attach(bag, lucia.J.handR, v3(0, -0.12, 0), [0, Math.PI / 2, 0]);
  const step = ease(prog(t, 83.0, 84.2));
  place(man, v3(MAR.x + 69.4 - step * 1.4, 1.18, MAR.z + 0.3), -Math.PI / 2); setPose(man, step < 1 ? P.walk(step * 4) : P.stand(t, 0.8));
  look(V(v3(x - 2.2, 1.65, MAR.z - 1.5), v3(x - 1.6, 1.62, MAR.z - 1.3), u), v3(MAR.x + 68, 1.8, MAR.z + 0.1), lerp(26, 20, u));
}, { tin: 'cut' });
shot2(86.6, 90.01, () => { look(v3(0, 1, 0), v3(0, 1, -1), 40); }, { tin: 'cut', black: true });

// ---------------------------------------------------------------- overlay (2D, drawn onto the final canvas)
function subtitleAt(t) { for (const l of TL.lines) if (t >= l.start - 0.05 && t < l.start + l.dur + 0.35) return l; return null; }
function wrapText(g, text, maxW) { const words = text.split(' '), lines = []; let cur = ''; for (const w of words) { const tst = cur ? cur + ' ' + w : w; if (g.measureText(tst).width > maxW && cur) { lines.push(cur); cur = w; } else cur = tst; } if (cur) lines.push(cur); return lines; }
function drawOverlay(t, shotFade) {
  const g = sctx;
  // cinematic bars
  g.fillStyle = '#000'; g.fillRect(0, 0, W, 96); g.fillRect(0, H - 96, W, 96);
  // title
  if (t < 5.6) {
    const a = clamp(prog(t, 0.6, 1.4)) * (1 - prog(t, 4.6, 5.6));
    g.save(); g.globalAlpha = a; g.textAlign = 'center';
    g.font = '400 92px Anton, Impact, sans-serif'; g.fillStyle = '#fff'; g.shadowColor = 'rgba(255,61,127,.9)'; g.shadowBlur = 30; g.fillText('THE VICE CITY DIARIES', W / 2, 330);
    g.shadowBlur = 0; g.font = '700 30px Inter, sans-serif'; g.fillStyle = '#ffd1e3'; g.fillText(E2 ? 'EPISODE 2 · NOWHERE TO RUN' : 'EPISODE 1 · THE GIRL WHO HAD NOTHING TO LOSE', W / 2, 390);
    g.font = '500 20px Inter, sans-serif'; g.fillStyle = 'rgba(255,255,255,.6)'; g.fillText('UNOFFICIAL FAN-MADE ANIMATION', W / 2, 430);
    g.restore();
  }
  // subtitles
  const l = subtitleAt(t);
  if (l) {
    const a = clamp((t - l.start + 0.05) / 0.15) * clamp((l.start + l.dur + 0.35 - t) / 0.2);
    g.save(); g.globalAlpha = a; g.textAlign = 'center';
    const vo = l.speaker === 'lucia_vo';
    g.font = `${vo ? 'italic ' : ''}700 50px Inter, sans-serif`;
    const lines = wrapText(g, l.text, 900);
    const y0 = H - 330 - (lines.length - 1) * 62;
    if (!vo) { g.font = '800 26px Inter, sans-serif'; g.fillStyle = (l.speaker === 'caller' || l.speaker === 'man') ? '#ff5470' : (l.speaker === 'jason' ? '#7fd6ff' : '#ffc6dd'); g.fillText(l.name, W / 2, y0 - 58); }
    g.font = `${vo ? 'italic ' : ''}700 50px Inter, sans-serif`; g.lineJoin = 'round';
    lines.forEach((ln, i) => { g.strokeStyle = 'rgba(0,0,0,.85)'; g.lineWidth = 10; g.strokeText(ln, W / 2, y0 + i * 62); g.fillStyle = '#fff'; g.fillText(ln, W / 2, y0 + i * 62); });
    g.restore();
  }
  // ending
  if (t >= 86.6) {
    const a = clamp(prog(t, 87.2, 88.0));
    g.fillStyle = '#000'; g.fillRect(0, 0, W, H);
    g.save(); g.textAlign = 'center'; g.globalAlpha = a;
    g.font = '400 110px Anton, Impact, sans-serif'; g.fillStyle = '#fff'; g.shadowColor = 'rgba(255,61,127,.9)'; g.shadowBlur = 36; g.fillText('TO BE CONTINUED…', W / 2, H / 2);
    g.shadowBlur = 0; g.globalAlpha = a * 0.6; g.font = '500 22px Inter, sans-serif'; g.fillStyle = '#fff';
    g.fillText('Unofficial fan-made animation · not affiliated with or endorsed by Rockstar Games', W / 2, H / 2 + 90);
    g.restore();
  }
}

// ---------------------------------------------------------------- frame
let lastShot = null;
function shotAt(t) { for (const s of SHOTS) if (t >= s.t0 && t < s.t1) return s; return SHOTS[SHOTS.length - 1]; }
function renderAt(t) {
  t = clamp(t, 0, DUR - 0.001);
  const s = shotAt(t), u = (t - s.t0) / (s.t1 - s.t0);
  // defaults each frame
  show(lucia.root, car, interior); hide(suv); jason.root.visible = true;
  lucia.J.spine.rotation.set(0, 0, 0);
  if (E2 || s.t0 < 12.1 || (s.t0 >= 27.8 && s.t0 < 75.5)) { scene.add(phone); phone.position.set(0, -50, 0); }
  hide(marina, man.root, overpass, conesG, usb); bag.add(usb); usb.position.set(0.02, 0.07, 0.01); usb.rotation.set(0, 0, 0);
  roadFill.intensity = 40; scene.fog.density = 0.0016; suvLight.intensity = 25; suvLight.distance = 60; sweepA.color.set(0xffd6a0); sweepA.distance = 9;
  car.userData.headlight.visible = true; car.userData.tail.visible = true; interior.add(bag);
  if (E2) { bag.userData.cash.position.set(0, 0.2, 0); bag.userData.cash.rotation.set(0, 0, 0); bag.userData.flaps.forEach(f => { f.rotation.x = 0; f.position.y = 0.245; }); }
  updateTraffic(t); roadFill2.position.set(2, 6, 204);
  updatePalms(boulevardPalms, t);
  if (!E2 && s.t0 < 27.8) { car.position.set(0, -50, 0); jason.root.visible = false; }
  setFace(jason, { blink: blinkAt(t, 0.6) });
  s.fn(t, u);
  { let d = 9; for (const h of [lucia, jason]) if (h.root.visible) d = Math.min(d, camera.position.distanceTo(headOf(h)));
    keyLight.intensity = 1.05 * clamp(d / 1.6, 0.3, 1.3) ** 1.2; rimLight.intensity = 1.4 * clamp(d / 1.6, 0.45, 1); }
  // transitions
  const since = t - s.t0, until = s.t1 - t;
  let blur = 0, fade = 0, flash = 0;
  if (s.tin === 'whip' && since < 0.22) blur = (1 - since / 0.22) * 1.0;
  const next = SHOTS[SHOTS.indexOf(s) + 1];
  if (next && next.tin === 'whip' && until < 0.18) blur = Math.max(blur, (1 - until / 0.18) * 1.0);
  if (s.tin === 'dip' && since < 0.35) fade = 1 - since / 0.35;
  if (next && next.tin === 'dip' && until < 0.3) fade = Math.max(fade, 1 - until / 0.3);
  if (t < 0.8) fade = Math.max(fade, 1 - t / 0.8);
  if (s.black) fade = 1;
  grade.uniforms.blur.value = blur; grade.uniforms.fade.value = fade; grade.uniforms.flash.value = flash; grade.uniforms.time.value = t;
  if (!s.black) composer.render(); else { renderer.setClearColor(0x000000); renderer.clear(); }
  sctx.drawImage(renderer.domElement, 0, 0, W, H);
  drawOverlay(t);
  lastShot = s;
}
window.renderAt = (t) => { renderAt(t); return true; };
window.__dbg = { lucia, jason, camera, keyLight, headOf, look, composer, setFace, scene };
window.EPISODE = { duration: DUR, ready: true };

// ---------------------------------------------------------------- playback (browser)
if (!RENDER) {
  const audio = new Audio(window.AUDIO_SRC || (E2 ? 'audio/soundtrack_ep2.m4a' : 'audio/soundtrack.m4a')); audio.preload = 'auto';
  const startEl = document.getElementById('start'), bar = document.querySelector('#prog > div'), status = document.getElementById('status');
  let playing = false, t0 = 0, clockStart = 0;
  const now = () => (audio.readyState >= 2 && !audio.paused ? audio.currentTime : (performance.now() - clockStart) / 1000 + t0);
  function play(from = 0) { startEl.style.display = 'none'; audio.currentTime = from; t0 = from; clockStart = performance.now(); audio.play().catch(() => {}); playing = true; }
  startEl.addEventListener('click', () => play(0));
  document.getElementById('replay').addEventListener('click', () => play(0));
  function loop() {
    const t = playing ? now() : 2.5;
    if (playing && t >= DUR) { playing = false; audio.pause(); startEl.style.display = 'flex'; }
    renderAt(Math.min(t, DUR - 0.01));
    bar.style.width = (100 * Math.min(t, DUR) / DUR) + '%';
    status.textContent = `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`;
    requestAnimationFrame(loop);
  }
  loop();
  // export: records the canvas + soundtrack in real time with MediaRecorder (MP4 where the browser supports it)
  if (window.NO_DOWNLOADS) {   // embedded viewers block downloads: point to the rendered MP4 instead
    const ex = document.getElementById('export'); ex.textContent = 'MP4: see chat'; ex.disabled = true; ex.title = 'Downloads are blocked here; the rendered MP4 is delivered separately';
  }
  document.getElementById('export').addEventListener('click', async () => {
    const types = ['video/mp4;codecs=avc1.640028,mp4a.40.2', 'video/mp4', 'video/webm;codecs=vp9,opus', 'video/webm'];
    const type = types.find(x => window.MediaRecorder && MediaRecorder.isTypeSupported(x));
    if (!type) { alert('This browser cannot record video. Use tools/render_mp4.cjs for a frame-exact MP4.'); return; }
    const ac = new AudioContext(); const src = ac.createMediaElementSource(audio); const dst = ac.createMediaStreamDestination(); src.connect(dst); src.connect(ac.destination);
    const stream = new MediaStream([...stage.captureStream(30).getVideoTracks(), ...dst.stream.getAudioTracks()]);
    const rec = new MediaRecorder(stream, { mimeType: type, videoBitsPerSecond: 12e6 }); const chunks = [];
    rec.ondataavailable = e => e.data.size && chunks.push(e.data);
    rec.onstop = () => { const blob = new Blob(chunks, { type }); const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'vice-city-diaries-ep1.' + (type.includes('mp4') ? 'mp4' : 'webm'); a.click(); };
    document.getElementById('export').textContent = '● Recording…';
    play(0); rec.start(500);
    setTimeout(() => { rec.stop(); document.getElementById('export').textContent = '⬇ Export MP4'; }, DUR * 1000 + 400);
  });
}
