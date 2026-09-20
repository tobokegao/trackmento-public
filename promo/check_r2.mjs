// 本番のページから /image-proxy を fetch して、R2 へ 302 で飛んでいるか（= Render の転送量に乗らないか）を確かめる
import { chromium } from "playwright";
const browser = await chromium.launch();
const ctx = await browser.newContext({ locale: "ja-JP" });
const page = await ctx.newPage();
const sizes = new Map();
page.on("response", async (r) => {
  const h = r.headers()["content-length"];
  const u = new URL(r.url());
  const key = u.hostname + (u.pathname.startsWith("/image-proxy") ? "/image-proxy" : u.pathname.split("/").slice(0, 2).join("/"));
  sizes.set(key, (sizes.get(key) || 0) + (h ? +h : 0));
});
await page.goto("https://trackmento.com/", { waitUntil: "networkidle" });
const out = await page.evaluate(async () => {
  const r = await fetch("/shares/1a01be848019.json");
  const d = await r.json();
  const urls = d.cells.filter(Boolean).map((c) => c.image).slice(0, 6);
  const res = [];
  for (const u of urls) {
    const rr = await fetch("/image-proxy?url=" + encodeURIComponent(u));
    res.push({ host: new URL(u).hostname, ok: rr.ok, redirected: rr.redirected, final: new URL(rr.url).hostname });
  }
  return res;
});
console.log(JSON.stringify(out, null, 1));
console.log("転送量（Content-Length の合計、バイト）:");
for (const [k, v] of [...sizes].sort((a, b) => b[1] - a[1]).slice(0, 8)) console.log(`  ${k}  ${v}`);
await ctx.close(); await browser.close();
