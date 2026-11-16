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

const TL = await (await fetch('data/timeline.json')).json();

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
function capsule(r, len, mat) { const m = new THREE.Mesh(new THREE.CapsuleGeometry(r, len, 6, 12), mat); return m; }
function joint(parent, x, y, z) { const j = new THREE.Group(); j.position.set(x, y, z); parent.add(j); return j; }
function makeHuman(spec) {
  const S = spec.scale || 1;
  const root = new THREE.Group(); root.scale.setScalar(S);
  const skin = new THREE.MeshStandardMaterial({ color: spec.skin, roughness: 0.55 });
  const top = new THREE.MeshStandardMaterial({ color: spec.jacket, roughness: spec.jacketRough ?? 0.45, metalness: spec.jacketMetal ?? 0.05 });
  const shirt = new THREE.MeshStandardMaterial({ color: spec.shirt, roughness: 0.7 });
  const legs = new THREE.MeshStandardMaterial({ color: spec.pants, roughness: 0.75 });
  const shoes = new THREE.MeshStandardMaterial({ color: spec.shoes, roughness: 0.5 });
  const hairM = new THREE.MeshStandardMaterial({ color: spec.hair, roughness: 0.55, metalness: 0.05 });
  const J = {};
  J.hips = joint(root, 0, 0.94, 0);
  const pelvis = new THREE.Mesh(new RoundedBoxGeometry(0.32, 0.18, 0.2, 3, 0.07), legs); J.hips.add(pelvis);
  J.spine = joint(J.hips, 0, 0.06, 0);
  const torso = new THREE.Mesh(new RoundedBoxGeometry(spec.chestW, 0.5, 0.21, 4, 0.08), top); torso.position.y = 0.25; J.spine.add(torso);
  const front = new THREE.Mesh(new RoundedBoxGeometry(0.12, 0.38, 0.02, 2, 0.008), shirt); front.position.set(0, 0.29, 0.106); J.spine.add(front);
  for (const sx of [-1, 1]) { const lap = new THREE.Mesh(new THREE.BoxGeometry(0.035, 0.36, 0.015), top); lap.position.set(sx * 0.075, 0.3, 0.112); lap.rotation.z = sx * 0.18; J.spine.add(lap); }
  J.neck = joint(J.spine, 0, 0.5, 0);
  const neck = capsule(0.045, 0.06, skin); neck.position.y = 0.04; J.neck.add(neck);
  J.head = joint(J.neck, 0, 0.13, 0.005);
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.105, 32, 24), skin); head.scale.set(0.9, 1.12, 1.0); head.position.y = 0.04; J.head.add(head);
  const jaw = new THREE.Mesh(new THREE.SphereGeometry(0.08, 24, 16), skin); jaw.scale.set(0.86, 0.72, 0.94); jaw.position.set(0, -0.032, 0.014); J.head.add(jaw);
  const nose = new THREE.Mesh(new THREE.SphereGeometry(0.011, 12, 8), skin); nose.scale.set(0.9, 1.5, 1.1); nose.position.set(0, 0.022, 0.1); J.head.add(nose);
  for (const sx of [-1, 1]) { const ear = new THREE.Mesh(new THREE.SphereGeometry(0.02, 10, 8), skin); ear.scale.set(0.5, 1.2, 0.9); ear.position.set(sx * 0.094, 0.035, 0.0); J.head.add(ear); }
  // eyes, brows, mouth
  const face = { eyes: [], irises: [], brows: [] };
  const white = new THREE.MeshStandardMaterial({ color: 0xf2efe8, roughness: 0.3 });
  const irisM = new THREE.MeshStandardMaterial({ color: spec.eyes || 0x2a1a10, roughness: 0.2 });
  const browM = new THREE.MeshStandardMaterial({ color: spec.brow || spec.hair, roughness: 0.8 });
  for (const sx of [-1, 1]) {
    const e = new THREE.Group(); e.position.set(sx * 0.037, 0.048, 0.084); J.head.add(e);
    const ew = new THREE.Mesh(new THREE.SphereGeometry(0.019, 16, 12), white); ew.scale.set(1.3, 0.82, 0.62); e.add(ew);
    const ir = new THREE.Mesh(new THREE.SphereGeometry(0.0105, 14, 10), irisM); ir.position.z = 0.0095; e.add(ir);
    const pup = new THREE.Mesh(new THREE.SphereGeometry(0.0045, 10, 8), new THREE.MeshBasicMaterial({ color: 0x050302 })); pup.position.z = 0.0062; ir.add(pup);
    const glint = new THREE.Mesh(new THREE.SphereGeometry(0.0018, 6, 6), new THREE.MeshBasicMaterial({ color: 0xffffff })); glint.position.set(0.003, 0.003, 0.009); ir.add(glint);
    const lid = new THREE.Mesh(new THREE.SphereGeometry(0.0205, 16, 12, 0, Math.PI * 2, 0, Math.PI / 2), skin); lid.scale.set(1.32, 0.88, 0.72); lid.rotation.x = -0.25; e.add(lid);
    const lash = new THREE.Mesh(new THREE.TorusGeometry(0.0215, 0.0022, 6, 16, Math.PI), browM); lash.scale.set(1.25, 0.75, 1); lash.position.z = 0.004; e.add(lash);
    const br = new THREE.Mesh(new RoundedBoxGeometry(0.042, 0.009, 0.01, 1, 0.004), browM); br.position.set(sx * 0.037, 0.08, 0.094); br.rotation.z = -sx * 0.08; J.head.add(br);
    face.eyes.push({ e, lid }); face.irises.push(ir); face.brows.push(br);
  }
  const lipM = new THREE.MeshStandardMaterial({ color: spec.lips, roughness: 0.4 });
  face.mouth = new THREE.Group(); face.mouth.position.set(0, -0.034, 0.093); J.head.add(face.mouth);
  face.upper = new THREE.Mesh(new RoundedBoxGeometry(0.042, 0.009, 0.012, 1, 0.004), lipM); face.mouth.add(face.upper);
  face.lower = new THREE.Mesh(new RoundedBoxGeometry(0.038, 0.01, 0.012, 1, 0.004), lipM); face.mouth.add(face.lower);
  face.inner = new THREE.Mesh(new THREE.BoxGeometry(0.034, 0.012, 0.004), new THREE.MeshBasicMaterial({ color: 0x1a0606 })); face.inner.position.z = -0.002; face.mouth.add(face.inner);
  // hair
  if (spec.hairStyle === 'long') {
    const cap = new THREE.Mesh(new THREE.SphereGeometry(0.117, 32, 20, 0, Math.PI * 2, 0, Math.PI * 0.5), hairM); cap.scale.set(0.97, 1.1, 1.08); cap.position.set(0, 0.05, -0.01); cap.rotation.x = -0.72; J.head.add(cap);
    const crown = new THREE.Mesh(new THREE.SphereGeometry(0.112, 32, 20, 0, Math.PI * 2, 0, Math.PI * 0.32), hairM); crown.scale.set(0.97, 1.1, 1.06); crown.position.set(0, 0.055, 0.0); J.head.add(crown);
    const back = new THREE.Mesh(new RoundedBoxGeometry(0.22, 0.34, 0.08, 4, 0.04), hairM); back.position.set(0, -0.09, -0.075); back.rotation.x = 0.1; J.head.add(back);
    for (const sx of [-1, 1]) { const s = new THREE.Mesh(new RoundedBoxGeometry(0.035, 0.24, 0.06, 3, 0.016), hairM); s.position.set(sx * 0.1, -0.05, -0.005); s.rotation.z = sx * 0.05; J.head.add(s); }
  } else {
    const cap = new THREE.Mesh(new THREE.SphereGeometry(0.111, 32, 20, 0, Math.PI * 2, 0, Math.PI * 0.42), hairM); cap.scale.set(0.95, 1.1, 1.05); cap.position.set(0, 0.05, -0.012); cap.rotation.x = -0.55; J.head.add(cap);
    const stub = new THREE.Mesh(new THREE.SphereGeometry(0.083, 24, 16, Math.PI * 0.15, Math.PI * 0.7, Math.PI * 0.52, Math.PI * 0.3), new THREE.MeshStandardMaterial({ color: 0x3a2a22, roughness: 0.9, transparent: true, opacity: 0.55 }));
    stub.scale.set(0.97, 0.77, 1.02); stub.position.set(0, -0.025, 0.02); stub.rotation.y = Math.PI; J.head.add(stub);
  }
  if (spec.earrings) for (const sx of [-1, 1]) { const ring = new THREE.Mesh(new THREE.TorusGeometry(0.014, 0.0025, 8, 20), new THREE.MeshStandardMaterial({ color: 0xd4a640, metalness: 1, roughness: 0.2 })); ring.position.set(sx * 0.096, 0.0, 0.005); ring.rotation.y = Math.PI / 2; J.head.add(ring); }
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
  const f = h.face;
  const o = clamp(mouth);
  f.inner.scale.y = 0.15 + o * 1.4; f.lower.position.y = -0.006 - o * 0.011; f.upper.position.y = 0.004 + o * 0.002;
  f.mouth.rotation.z = smirk * 0.12;
  f.eyes.forEach(({ lid }, i) => { lid.rotation.x = lerp(-0.25, 1.35, clamp(blink)); });
  f.irises.forEach(ir => { ir.position.x = look[0] * 0.006; ir.position.y = look[1] * 0.004; });
  f.brows.forEach((b, i) => { const sx = i ? 1 : -1; b.position.y = 0.078 + brow * 0.006; b.rotation.z = -sx * (0.08 - brow * 0.18); });
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
  hair: 0x1a110d, hairStyle: 'long', lips: 0x8a4a46, eyes: 0x3a220f, chestW: 0.33, earrings: true, scale: 1.0 });
const jason = makeHuman({ skin: 0xb88a6e, jacket: 0x3d4430, jacketRough: 0.7, shirt: 0x26262b, pants: 0x22252d, shoes: 0x3a2a20,
  hair: 0x2a1d16, hairStyle: 'short', lips: 0x8e5a4e, eyes: 0x2a2014, chestW: 0.38, scale: 1.06 });
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
      g.font = '800 26px Inter'; g.fillStyle = '#fff';
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
const roadFill2 = new THREE.PointLight(0x9fb4ff, 30, 30, 1.3); DRIVE.add(roadFill2);
const sweepB = new THREE.PointLight(0xff3d9a, 0, 10, 1.4); DRIVE.add(sweepB);
const sweepC = new THREE.PointLight(0x22d6ff, 0, 10, 1.4); DRIVE.add(sweepC);

// distance travelled by the hero car in the drive set (integral of its speed)
function speedAt(t) { if (t < 44.6) return 0; if (t < 47) return lerp(0, 24, ease(prog(t, 44.6, 47))); if (t < 83.5) return 24; return lerp(24, 36, ease(prog(t, 83.5, 86))); }
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

// 0) AERIAL — the city that never sleeps
shot(0, 6.6, (t, u) => {
  const p = V(v3(-420, 300, 420), v3(30, 120, 120), ease(u));
  const tgt = V(v3(0, 40, -40), v3(HERO.x, BALC_Y, HERO.z), ease(u));
  look(p, tgt, lerp(55, 42, u));
  luciaBalcony(t, 'rail');
  setFace(lucia, { blink: blinkAt(t, 0.2) });
});
// 1) Balcony, over the shoulder, city below
shot(6.6, 9.6, (t, u) => {
  const b = BALC();
  luciaBalcony(t, 'rail');
  setFace(lucia, { blink: blinkAt(t, 0.2), brow: -0.3 });
  const hd = headOf(lucia), yaw = lucia.root.rotation.y, dir = v3(Math.sin(yaw), 0, Math.cos(yaw)), perp = v3(dir.z, 0, -dir.x);
  const cam = hd.clone().addScaledVector(dir, -lerp(1.35, 1.0, ease(u))).addScaledVector(perp, 0.32).add(v3(0, 0.1, 0));
  look(cam.add(handheld(t)), hd.clone().addScaledVector(dir, 40).addScaledVector(perp, -6).add(v3(0, -11, 0)), 46);
}, { tin: 'whip' });
// 2) Lucia front, takes a cigarette but doesn't light it
shot(9.6, 12.1, (t, u) => {
  const b = BALC();
  const cu = prog(t, 9.9, 11.4);
  luciaBalcony(t, { cig: cu });
  if (cu > 0.5) { attach(cig, lucia.J.handR, v3(0, -0.06, 0.04), [0, 0, Math.PI / 2]); show(cig); } else hide(cig);
  setFace(lucia, { blink: blinkAt(t, 0.2), brow: -0.4, look: [0.3, -0.2] });
  const head = new THREE.Vector3(); lucia.J.head.getWorldPosition(head);
  look(v3(b.x - 5.1, b.y + 1.65, b.z + 1.0).add(handheld(t)), head.clone().add(v3(0, -0.08, 0)), lerp(30, 26, u));
}, { tin: 'cut' });
// 3) The phone on the table lights up
shot(12.1, 14.6, (t, u) => {
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
shot(14.6, 19.3, (t, u) => {
  const b = BALC();
  luciaBalcony(t, { phone: ease(prog(t, 14.6, 15.1)) });
  attach(phone, lucia.J.handR, v3(0.0, -0.08, 0.03), [0.1, Math.PI / 2, 0]); setPhone('incall', t - 14.6);
  hide(cig);
  talk(lucia, 'lucia', t, { brow: -0.35, look: [0.4, 0] });
  const head = new THREE.Vector3(); lucia.J.head.getWorldPosition(head);
  look(v3(b.x - 5.2, b.y + 1.62, b.z + 2.6 - u * 0.3).add(handheld(t)), head.clone().add(v3(0, -0.04, 0)), 28);
}, { tin: 'cut' });
shot(19.3, 23.5, (t, u) => {
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
shot(23.5, 24.4, (t, u) => {
  const b = BALC();
  luciaBalcony(t, { phone: 1 });
  look(v3(b.x - 4.4, b.y + 1.6, b.z + 1.2), v3(b.x - 30, 0, b.z + 8 - u * 6), lerp(38, 30, u));
}, { tin: 'cut' });
// 6) "Then I guess you should come find me." — hangs up
shot(24.4, 27.8, (t, u) => {
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
shot(27.8, 31.6, (t, u) => {
  hide(lucia.root); show(jason.root);
  carArrive(t);
  placeInCar(t);
  const c = CURB();
  look(v3(c.x - 6.5, 0.7, c.z - 6 + u * 2).add(handheld(t, 0.6)), v3(car.position.x, 0.9, car.position.z), lerp(34, 30, u));
}, { tin: 'whip', world: 'city' });
// Lucia walks out to the car and gets in
shot(31.6, 35.4, (t, u) => {
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
function inCar(t, inside = true) {
  show(lucia.root, jason.root, car, interior);
  car.userData.cabin.visible = !inside; car.userData.tail.visible = !inside;
  car.position.set(DRIVE.position.x, 0, DRIVE.position.z); car.rotation.set(0, Math.PI, 0);
  updateDrive(t);
  car.userData.wheels.forEach(w => (w.rotation.x = distAt(t) * 2.8));
  placeInCar(t);
  bag.position.set(-0.42, 0.62, 0.2); bag.rotation.set(0, 0.2, 0);
}
const carPt = (x, y, z) => v3(x, y, z).applyQuaternion(car.quaternion).add(car.position);
shot(35.4, 38.7, (t, u) => {        // two-shot through the windscreen
  inCar(t);
  jason.J.head.rotation.y = -0.45 * ease(prog(t, 35.5, 36.0));
  talk(jason, 'jason', t, { brow: 0.4, look: [-0.6, 0] }); talk(lucia, 'lucia', t, { brow: -0.3, look: [-0.3, 0] });
  look(carPt(0, 1.26, 1.45).add(handheld(t, 0.4)), carPt(0, 1.12, -0.2), lerp(74, 68, u));
}, { tin: 'dip', world: 'drive' });
shot(38.7, 41.2, (t, u) => {        // Lucia, over Jason's shoulder
  inCar(t);
  lucia.J.head.rotation.y = 0.45; jason.J.head.rotation.y = -0.5;
  talk(lucia, 'lucia', t, { brow: -0.4, look: [0.5, 0] }); talk(jason, 'jason', t, {});
  look(carPt(0.62, 1.22, 0.12).add(handheld(t, 0.5)), headOf(lucia).add(v3(0, -0.03, 0)), 28);
}, { tin: 'cut', world: 'drive' });
shot(41.2, 42.4, (t, u) => {        // Jason: "What did you do?"
  inCar(t);
  jason.J.head.rotation.y = -0.55; lucia.J.head.rotation.y = 0.4;
  talk(jason, 'jason', t, { brow: 0.6, look: [-0.5, 0] });
  look(carPt(-0.55, 1.22, 0.25).add(handheld(t, 0.5)), headOf(jason).add(v3(0, -0.03, 0)), 28);
}, { tin: 'cut', world: 'drive' });
shot(42.4, 45.0, (t, u) => {        // Lucia looks ahead
  inCar(t);
  lucia.J.head.rotation.y = lerp(0.4, 0, ease(prog(t, 43.6, 44.4))); jason.J.head.rotation.y = -0.5;
  talk(lucia, 'lucia', t, { brow: -0.5, look: [0, 0] });
  look(carPt(-0.2, 1.25, 1.0).add(handheld(t, 0.4)), headOf(lucia).add(v3(0, -0.03, 0)), lerp(26, 23, u));
}, { tin: 'cut', world: 'drive' });
shot(45.0, 47.3, (t, u) => {        // exterior: the car speeds away
  inCar(t, false);
  const d0 = distAt(45.0), d = distAt(t);
  look(v3(DRIVE.position.x + 4.2, 0.9, DRIVE.position.z + 4 + (d - d0)), carPt(0, 0.7, 0), lerp(42, 34, u));
}, { tin: 'whip', world: 'drive' });
shot(47.3, 52.4, (t, u) => {        // "Lucia, what's in the bag?"
  inCar(t);
  jason.J.head.rotation.y = -0.4 * (Math.sin(t * 0.9) > -0.2 ? 1 : 0.3); lucia.J.head.rotation.y = -0.6;  // she looks out of her window
  talk(jason, 'jason', t, { brow: 0.5, look: [-0.6, 0] }); talk(lucia, 'lucia', t, { brow: -0.4, look: [-0.6, 0] });
  look(carPt(0.03, 1.26, 1.45).add(handheld(t, 0.5)), carPt(-0.02, 1.12, -0.2), lerp(72, 64, u));
}, { tin: 'cut', world: 'drive' });
shot(52.4, 55.6, (t, u) => {        // the bag opens: cash and a phone
  inCar(t);
  lucia.J.head.rotation.x = 0.5; lucia.J.head.rotation.y = 0;
  const open = ease(prog(t, 52.7, 54.0));
  bag.userData.flaps[0].rotation.x = -open * 1.4; bag.userData.flaps[0].position.y = 0.245 + open * 0.05;
  bag.userData.flaps[1].rotation.x = open * 1.4; bag.userData.flaps[1].position.y = 0.245 + open * 0.05;
  bag.userData.cash.position.y = 0.12 + open * 0.1;
  const bp = carPt(-0.42, 0.78, 0.2);
  look(v3(bp.x, bp.y + 0.55 - u * 0.1, bp.z).add(carPt(0, 0, 0.18).sub(car.position)), bp, lerp(42, 34, u));
}, { tin: 'cut', world: 'drive' });
shot(55.6, 57.3, (t, u) => {
  inCar(t); bag.userData.cash.position.y = 0.22;
  jason.J.head.rotation.y = -0.55;
  talk(jason, 'jason', t, { brow: 0.8, look: [-0.5, -0.2] });
  look(carPt(-0.5, 1.2, 0.3).add(handheld(t, 0.5)), headOf(jason).add(v3(0, -0.03, 0)), 27);
}, { tin: 'cut', world: 'drive' });
shot(57.3, 61.2, (t, u) => {
  inCar(t); bag.userData.cash.position.y = 0.22;
  lucia.J.head.rotation.y = lerp(0.1, 0.45, ease(prog(t, 57.3, 58)));
  talk(lucia, 'lucia', t, { brow: -0.2, smirk: ease(prog(t, 59.8, 60.8)) * 0.8, look: [0.5, 0] });
  look(carPt(0.55, 1.22, 0.2).add(handheld(t, 0.5)), headOf(lucia).add(v3(0, -0.03, 0)), lerp(27, 23, u));
}, { tin: 'cut', world: 'drive' });
// --- SUV
function suvAt(t) {
  roadFill2.position.set(2, 6, 0);
  const gap = t < 61 ? 400 : t < 70 ? lerp(300, 60, ease(prog(t, 61, 70))) : lerp(60, 11, ease(prog(t, 70, 84)));
  suv.position.set(DRIVE.position.x + 1.2 * Math.sin(t * 0.7), 0, DRIVE.position.z + gap); suv.rotation.set(0, Math.PI, 0);
  suv.userData.wheels.forEach(w => (w.rotation.x = t * 30));
  roadFill2.position.set(suv.position.x - DRIVE.position.x + 2, 6, gap * 0.5 + 4);
  return gap;
}
shot(61.2, 64.9, (t, u) => {        // through the rear window: headlights appear
  inCar(t); bag.userData.cash.position.y = 0.22; show(suv); suvAt(t);
  look(carPt(0, 1.25, 0.6), carPt(0, 1.05, -8), 32);
}, { tin: 'cut', world: 'drive' });
shot(64.9, 68.6, (t, u) => {        // rear-view mirror + Jason
  inCar(t); show(suv); const gap = suvAt(t);
  drawMirror(clamp(1 - gap / 260) * 1.2 + 0.25, t);
  jason.J.head.rotation.x = -0.1; jason.J.head.rotation.y = -0.1;
  talk(jason, 'jason', t, { brow: 0.9, look: [-0.2, 0.5] });
  look(carPt(0.12, 1.27, 0.5).add(handheld(t, 0.4)), carPt(0.02, 1.33, 0.82), lerp(36, 30, u));
}, { tin: 'cut', world: 'drive' });
shot(68.6, 71.2, (t, u) => {        // Lucia turns around
  inCar(t); show(suv); suvAt(t);
  const turn = ease(prog(t, 68.7, 69.8));
  lucia.J.spine.rotation.y = turn * 0.7; lucia.J.head.rotation.y = turn * 1.0; lucia.J.head.rotation.x = -0.05;
  setFace(lucia, { blink: blinkAt(t, 0.2), brow: 0.3 * turn, look: [0.6 * turn, 0] });
  look(carPt(0.05, 1.28, -0.85).add(handheld(t, 0.6)), headOf(lucia).add(v3(0, -0.02, 0)), 34);
}, { tin: 'cut', world: 'drive' });
shot(71.2, 75.5, (t, u) => {        // exterior chase
  inCar(t); show(suv); suvAt(t);
  inCar(t, false);
  const gap = suvAt(t);
  const p = carPt(1.6 - u * 0.8, 1.9 + u * 0.3, -gap - 7.5);
  look(p.add(handheld(t, 1.4)), carPt(0, 0.9, 0), lerp(30, 26, u));
}, { tin: 'whip', world: 'drive' });
shot(75.5, 80.6, (t, u) => {        // the message
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
shot(80.6, 84.0, (t, u) => {        // "Keep driving."
  inCar(t); show(suv); suvAt(t);
  attach(phone, lucia.J.handR, v3(0, -0.07, 0.04), [-0.4, 0, 0]); setPhone('off', t);
  lucia.J.head.rotation.y = ease(prog(t, 80.7, 81.5)) * 0.5;
  talk(lucia, 'lucia', t, { brow: -0.6, look: [0.7, 0] });
  look(carPt(0.58, 1.22, 0.25).add(handheld(t, 0.4)), headOf(lucia).add(v3(0, -0.03, 0)), lerp(26, 20, u));
}, { tin: 'cut', world: 'drive' });
shot(84.0, 86.6, (t, u) => {        // the car pulls away, the SUV right behind
  inCar(t); show(suv); suvAt(t);
  inCar(t, false);
  const gap = suvAt(t);
  look(carPt(-2.5, 4.5 + u * 4, -gap - 14 - u * 8), carPt(0, 0.6, 6), lerp(34, 40, u));
}, { tin: 'whip', world: 'drive' });
shot(86.6, 90.01, () => { look(v3(0, 1, 0), v3(0, 1, -1), 40); }, { tin: 'cut', black: true });

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
    g.shadowBlur = 0; g.font = '700 30px Inter, sans-serif'; g.fillStyle = '#ffd1e3'; g.fillText('EPISODE 1 · THE GIRL WHO HAD NOTHING TO LOSE', W / 2, 390);
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
    if (!vo) { g.font = '800 26px Inter, sans-serif'; g.fillStyle = l.speaker === 'caller' ? '#ff5470' : (l.speaker === 'jason' ? '#7fd6ff' : '#ffc6dd'); g.fillText(l.name, W / 2, y0 - 58); }
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
  if (s.t0 < 12.1 || (s.t0 >= 27.8 && s.t0 < 75.5)) { scene.add(phone); phone.position.set(0, -50, 0); }
  updateTraffic(t);
  updatePalms(boulevardPalms, t);
  if (s.t0 < 27.8) { car.position.set(0, -50, 0); jason.root.visible = false; }
  setFace(jason, { blink: blinkAt(t, 0.6) });
  s.fn(t, u);
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
window.EPISODE = { duration: DUR, ready: true };

// ---------------------------------------------------------------- playback (browser)
if (!RENDER) {
  const audio = new Audio(window.AUDIO_SRC || 'audio/soundtrack.m4a'); audio.preload = 'auto';
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
