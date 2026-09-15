// つまみの握り模様だけを見るための見本を作って撮る（実際のトークンを使う）
import { chromium } from "playwright";
const out = process.argv[2];
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 520, height: 260 }, deviceScaleFactor: 4, locale: "ja-JP" });
const page = await ctx.newPage();
await page.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
await page.waitForTimeout(2500);
await page.evaluate(() => {
  const box = document.createElement("div");
  box.id = "probe";
  box.style.cssText = "position:fixed;inset:0;z-index:99999;background:var(--color-paper);display:flex;gap:28px;align-items:center;justify-content:center";
  // スライダーのつまみ（横バー用）と、スクロールバーのつまみ（縦バー用）を並べる
  const slider = document.querySelector('input[type="range"]');
  const st = slider ? getComputedStyle(slider, "::-webkit-slider-thumb") : null;
  const mk = (w, h, cls) => { const d = document.createElement("div"); d.className = cls; d.style.cssText = `width:${w}px;height:${h}px`; return d; };
  box.append(mk(18, 18, "probe-h"), mk(24, 80, "probe-v"));
  const css = document.createElement("style");
  css.textContent = `
  .probe-h, .probe-v { background-color: var(--color-bar); border: 1px solid var(--color-bar-dark); background-repeat: no-repeat; }
  .probe-h { background-image:
    linear-gradient(var(--color-hl-dim), var(--color-hl-dim)), linear-gradient(var(--color-hl-dim), var(--color-hl-dim)),
    repeating-linear-gradient(to right, #fff 0 1px, transparent 1px 3px),
    repeating-linear-gradient(to right, var(--color-hl-dim) 0 1px, transparent 1px 3px),
    repeating-linear-gradient(to right, transparent 0 1px, var(--color-bar-dark) 1px 2px, transparent 2px 3px),
    linear-gradient(#fff, #fff), linear-gradient(#fff, #fff);
    background-size: 1px 1px, 1px 1px, 9px 1px, 9px 8px, 9px 8px, 100% 1px, 1px 100%;
    background-position: right 0 top 0, left 0 bottom 0, center 4px, center 5px, center 5px, left top, left top; }
  .probe-v { background-image:
    linear-gradient(var(--color-hl-dim), var(--color-hl-dim)), linear-gradient(var(--color-hl-dim), var(--color-hl-dim)),
    repeating-linear-gradient(to bottom, #fff 0 2px, transparent 2px 6px),
    repeating-linear-gradient(to bottom, var(--color-hl-dim) 0 2px, transparent 2px 6px),
    repeating-linear-gradient(to bottom, transparent 0 2px, var(--color-bar-dark) 2px 4px, transparent 4px 6px),
    linear-gradient(#fff, #fff), linear-gradient(#fff, #fff);
    background-size: 1px 1px, 1px 1px, 2px 16px, 12px 16px, 12px 16px, 100% 1px, 1px 100%;
    background-position: right 0 top 0, left 0 bottom 0, center 32px, center 32px, center 32px, left top, left top; }`;
  document.head.append(css);
  document.body.append(box);
});
await page.waitForTimeout(400);
await page.screenshot({ path: out });
await ctx.close(); await browser.close();
