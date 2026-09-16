/* 撮影用の「見えるカーソル」。**スクリーンショットにシステムのカーソルは写らない**
   （OS が画面に重ねているだけで、ページの絵ではないため）。そこで自前で描く。

   - 矢印は Mac OS 9 風の白黒（サイトの見た目に合わせる）
   - 押した瞬間に輪が広がる（クリック／タップの合図）
   - 押しているあいだは矢印を少し傾けて、掴んでいることを示す
   - 指で触る画面（hasTouch）では矢印ではなく**指の丸**にする

   page.addInitScript() で入れる。pointer-events: none なので操作の邪魔はしない。 */
(() => {
  const NS = "http://www.w3.org/2000/svg";
  const touch = matchMedia("(pointer: coarse)").matches;

  const wrap = document.createElement("div");
  wrap.id = "__shotcursor";
  wrap.style.cssText = "position:fixed;left:0;top:0;width:0;height:0;z-index:2147483647;pointer-events:none;";

  // 押した合図の輪
  const ring = document.createElement("div");
  ring.style.cssText =
    "position:absolute;left:0;top:0;width:12px;height:12px;margin:-6px 0 0 -6px;border-radius:50%;" +
    "border:3px solid #e5462c;opacity:0;transform:scale(1);";

  // 矢印（PC）／指の丸（スマホ）
  let tip;
  if (touch) {
    tip = document.createElement("div");
    tip.style.cssText =
      "position:absolute;left:0;top:0;width:34px;height:34px;margin:-17px 0 0 -17px;border-radius:50%;" +
      "background:rgba(229,70,44,.28);border:3px solid #e5462c;box-sizing:border-box;";
  } else {
    tip = document.createElementNS(NS, "svg");
    tip.setAttribute("width", "22");
    tip.setAttribute("height", "30");
    tip.setAttribute("viewBox", "0 0 22 30");
    tip.style.cssText = "position:absolute;left:0;top:0;transform-origin:2px 1px;filter:drop-shadow(1px 2px 0 rgba(0,0,0,.35));";
    const p = document.createElementNS(NS, "path");
    p.setAttribute("d", "M2 1 L2 22 L7.5 17 L11 25.5 L15 24 L11.5 15.5 L19 15 Z");
    p.setAttribute("fill", "#fff");
    p.setAttribute("stroke", "#111");
    p.setAttribute("stroke-width", "2");
    p.setAttribute("stroke-linejoin", "round");
    tip.append(p);
  }

  wrap.append(ring, tip);
  const put = () => (document.body || document.documentElement).append(wrap);
  if (document.body) put(); else addEventListener("DOMContentLoaded", put);

  let x = -100, y = -100, down = false;
  const draw = () => {
    tip.style.transform = touch
      ? `translate(${x}px, ${y}px)`
      : `translate(${x - 2}px, ${y - 1}px)` + (down ? " rotate(-12deg)" : "");
    ring.style.transform = `translate(${x}px, ${y}px) scale(${ring.dataset.s || 1})`;
  };
  const move = (e) => { x = e.clientX; y = e.clientY; draw(); };

  // 押した合図: 小さい輪が 1 回広がって消える
  let t0 = 0;
  const pulse = () => {
    t0 = performance.now();
    const step = () => {
      const k = Math.min(1, (performance.now() - t0) / 420);
      ring.dataset.s = String(1 + k * 3.2);
      ring.style.opacity = String(1 - k);
      draw();
      if (k < 1) requestAnimationFrame(step);
    };
    step();
  };

  // **pointer イベントで追う**（mouse イベントではない）。つまみやスクロールバーは
  // setPointerCapture で pointer を掴むので、掴まれている間は mousemove が追いつかず、
  // 矢印や丸がつまみから離れて置き去りになった（撮影して分かった）
  addEventListener("pointermove", move, true);
  addEventListener("pointerdown", (e) => { move(e); down = true; pulse(); }, true);
  addEventListener("pointerup", (e) => { move(e); down = false; draw(); }, true);
  // **HTML5 のドラッグ中は mousemove が来ない**（ブラウザが drag / dragover に切り替える）。
  // そちらからも位置を拾わないと、掴んだ場所に矢印が置き去りになる
  addEventListener("dragover", move, true);
  addEventListener("dragend", (e) => { move(e); down = false; draw(); }, true);
  addEventListener("drop", (e) => { move(e); down = false; draw(); }, true);
  draw();
})();
