// 市松の描き方を 3 通り比べる（dpr 2.625）
import { chromium } from "playwright";
const html = `<!doctype html><meta charset=utf-8><style>
body{margin:0;background:#f2efe6;padding:20px;font:12px sans-serif}
.box{position:relative;width:60px;height:30px;border:2px solid #121a1f;background:#f7f5f0;margin:0 0 26px}
.box::after{content:"";position:absolute;inset:-2px;transform:translate(var(--sh),var(--sh));
  clip-path:polygon(calc(100% - var(--sh)) 0,100% 0,100% 100%,0 100%,0 calc(100% - var(--sh)),calc(100% - var(--sh)) calc(100% - var(--sh)));}
:root{--dot:1px;--sh:calc(2*var(--dot))}
.a::after{background:repeating-conic-gradient(#121a1f 0 25%, transparent 0 50%) right bottom/calc(2*var(--dot)) calc(2*var(--dot))}
.b::after{background-color:#121a1f;
  -webkit-mask-image:var(--m);mask-image:var(--m);
  -webkit-mask-size:calc(2*var(--dot)) calc(2*var(--dot));mask-size:calc(2*var(--dot)) calc(2*var(--dot));
  -webkit-mask-position:right bottom;mask-position:right bottom;
  -webkit-mask-repeat:repeat;mask-repeat:repeat}
:root{--m:url('data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="2" height="2" shape-rendering="crispEdges"><rect width="1" height="1" fill="%23fff"/><rect x="1" y="1" width="1" height="1" fill="%23fff"/></svg>')}
.snap{--dot:1.1429px}
.off{margin-top:0.4px}
</style>
<div class=box class-a></div>
<div class="box a">conic 1px</div>
<div class="box a snap">conic snap</div>
<div class="box b">mask 1px</div>
<div class="box b snap">mask snap</div>
<div class="box b snap off">mask snap ずれ</div>`;
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 300, height: 400 }, deviceScaleFactor: 2.625 });
const page = await ctx.newPage();
await page.setContent(html);
await page.waitForTimeout(400);
const bs = await page.evaluate(() => [...document.querySelectorAll(".box")].slice(1).map(b => { const r = b.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height, t: b.textContent }; }));
for (const [i, b] of bs.entries())
  await page.screenshot({ path: `C:/Users/amisi/AppData/Local/Temp/claude/d_${i}.png`, clip: { x: b.x + b.w - 10, y: b.y - 2, width: 16, height: 18 } });
console.log(JSON.stringify(bs.map(b => [b.t, b.y])));
await ctx.close(); await browser.close();
