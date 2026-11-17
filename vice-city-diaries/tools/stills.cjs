// node tools/stills.cjs <out.png> t1 t2 ...   (needs a static server on :8765 serving this folder)
const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const [out, ...ts] = process.argv.slice(2);
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const p = await b.newPage({ viewport: { width: 1080, height: 1920 } });
  p.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') console.log('console:', m.text().slice(0, 300)); });
  p.on('pageerror', e => console.log('pageerror:', e.message));
  await p.goto('http://localhost:8765/index.html?render=1' + (process.env.EP ? '&ep=' + process.env.EP : ''));
  await p.waitForFunction(() => window.EPISODE && window.EPISODE.ready, null, { timeout: 120000 });
  await p.evaluate(() => document.fonts.ready);
  const shots = [];
  for (const t of ts) {
    const t0 = Date.now();
    await p.evaluate(t => window.renderAt(t), parseFloat(t));
    const data = await p.evaluate(() => document.getElementById('stage').toDataURL('image/jpeg', 0.85));
    shots.push(Buffer.from(data.split(',')[1], 'base64'));
    console.log('t', t, (Date.now() - t0) + 'ms');
  }
  ts.forEach((t, i) => fs.writeFileSync(`${out}_${String(i).padStart(2, '0')}.jpg`, shots[i]));
  await b.close();
})();
