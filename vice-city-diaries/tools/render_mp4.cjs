// Frame-exact MP4 render of the episode.
//   1) serve this folder:   python3 -m http.server 8765
//   2) render frames:       node tools/render_mp4.cjs <startFrame> <endFrame> <out.mp4>   (video only, 30 fps, 1080x1920)
//   3) add the soundtrack:  ffmpeg -i video.mp4 -i soundtrack.wav -map 0:v -map 1:a -c:v copy -c:a aac -shortest final.mp4
// Run several ranges in parallel and concat them for speed (see README).
const { chromium } = require('playwright');
const { spawn } = require('child_process');
(async () => {
  const [a, b, out] = process.argv.slice(2);
  const port = process.env.PORT || 8765;
  const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const page = await browser.newPage({ viewport: { width: 1080, height: 1920 } });
  page.on('pageerror', e => console.error('pageerror:', e.message));
  await page.goto(`http://localhost:${port}/index.html?render=1${process.env.EP ? "&ep=" + process.env.EP : ""}`);
  await page.waitForFunction(() => window.EPISODE && window.EPISODE.ready, null, { timeout: 120000 });
  await page.evaluate(() => document.fonts.ready);
  const ff = spawn('ffmpeg', ['-y', '-v', 'error', '-f', 'image2pipe', '-framerate', '30', '-c:v', 'mjpeg', '-i', '-',
    '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p', '-r', '30', out], { stdio: ['pipe', 'inherit', 'inherit'] });
  const t0 = Date.now();
  for (let f = +a; f < +b; f++) {
    const data = await page.evaluate(t => { window.renderAt(t); return document.getElementById('stage').toDataURL('image/jpeg', 0.93); }, f / 30);
    const buf = Buffer.from(data.slice(data.indexOf(',') + 1), 'base64');
    if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
    if ((f - a) % 60 === 0) console.log(`[${a}-${b}] frame ${f}  ${((Date.now() - t0) / 1000 / Math.max(1, f - a + 1)).toFixed(2)}s/frame`);
  }
  ff.stdin.end();
  await new Promise(r => ff.on('close', r));
  await browser.close();
})();
