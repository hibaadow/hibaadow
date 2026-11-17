// Resumable frame renderer: node tools/render_frames.cjs <outDir> <worker> <workers>
// Renders frames f where f % workers == worker, saving JPEGs; existing frames are skipped (safe to restart).
// Encode afterwards: ffmpeg -framerate 30 -i <outDir>/%05d.jpg -i soundtrack.wav -c:v libx264 -crf 18 -pix_fmt yuv420p -c:a aac -shortest out.mp4
const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const [dir, k, n] = process.argv.slice(2); const K = +k, NW = +n;
  fs.mkdirSync(dir, { recursive: true });
  const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const page = await browser.newPage({ viewport: { width: 1080, height: 1920 } });
  await page.goto(`http://localhost:${process.env.PORT || 8765}/index.html?render=1${process.env.EP ? '&ep=' + process.env.EP : ''}`);
  await page.waitForFunction(() => window.EPISODE && window.EPISODE.ready, null, { timeout: 180000 });
  await page.evaluate(() => document.fonts.ready);
  const total = Math.round(await page.evaluate(() => window.EPISODE.duration) * 30);
  for (let f = K; f < total; f += NW) {
    const file = `${dir}/${String(f).padStart(5, '0')}.jpg`;
    if (fs.existsSync(file)) continue;
    const data = await page.evaluate(t => { window.renderAt(t); return document.getElementById('stage').toDataURL('image/jpeg', 0.93); }, f / 30);
    fs.writeFileSync(file + '.tmp', Buffer.from(data.slice(data.indexOf(',') + 1), 'base64')); fs.renameSync(file + '.tmp', file);
  }
  await browser.close();
})();
