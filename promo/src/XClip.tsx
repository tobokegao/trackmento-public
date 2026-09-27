// X に載せる 1 機能 1 本の短い動画（2026-09-25）。素材は promo/x_clips.mjs が撮った
// public/xclips/<id>/take.mp4（画面ぜんぶ、30 コマ/秒、倍率 2）と events.json（カメラ・カーソル・押した印）。
//
// ここでするのは画面の外側の演出だけ（画面そのものは本物の録画。作り直すとサイトとずれるため）:
// - カメラ … 印の四角に寄る（16:9 に広げ、2 倍まで。録画の外は映さない）。移るときは加速・減速する
// - カーソル … 印の点から点へなめらかに運ぶ（Mac OS 9 風の白黒の矢印。promo/cursor.js と同じ形）
// - 押した合図 … 押した所に輪が 1 回広がる
// - 押したキー … 画面の下に OS 9 風のキーの絵で出す（キーボードの操作は画面に跡が残らず、ひとりでに動いたように見えるため。
//   2026-09-25、利用者の指摘「元に戻すがクリックされていないように見える」）
// - 終わり … 最後の絵に最初の絵を溶かし込んで、繰り返し再生のつなぎ目を消す
import React from "react";
import { AbsoluteFill, CalculateMetadataFunction, Easing, Freeze, OffthreadVideo, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { loadFont } from "@remotion/fonts";

loadFont({ family: "XKey", url: staticFile("fonts/DotGothic16-Regular.ttf"), weight: "400" });
loadFont({ family: "XPlex", url: staticFile("fonts/IBMPlexSansJP-Bold.ttf"), weight: "700" });
loadFont({ family: "XMark", url: staticFile("fonts/TrackmentoMark-Bold.ttf"), weight: "700" });
loadFont({ family: "XSilk", url: staticFile("fonts/Silkscreen-Regular.ttf"), weight: "400" });

type Rect = { x: number; y: number; w: number; h: number };
type Ev =
  | { f: number; type: "cam"; rect: Rect; dur: number }
  | { f: number; type: "cursor"; x: number; y: number; dur: number }
  | { f: number; type: "down"; x: number; y: number; ring?: boolean }
  | { f: number; type: "hide" }
  | { f: number; type: "key"; key: string }
  | { f: number; type: "touches"; pts: { x: number; y: number }[] };   // 2 本指（clip_kit の pinch）。空の配列で指を離す
export type Take = { id: string; fps: number; frames: number; vw: number; vh: number; dpr: number; twin?: boolean; events: Ev[] };
export type XClipProps = { id: string; take?: Take; lang?: "ja" | "en"; title?: string; phoneMode?: "frame" | "fill" };

const LOOP = 15;      // 終わりに最初の絵を溶かし込むコマ数（0.5 秒）
const MAX_ZOOM = 2;   // 録画は倍率 2 なので、2 倍まではぼやけない
const PAD = 28;       // 寄る四角のまわりに残す余白（画面の CSS px）
const ease = Easing.bezier(0.45, 0, 0.2, 1);

/** 印の四角を、映す箱と同じ縦横比 A の「映す範囲」にする（横の動画は A＝画面の比。縦の動画は箱が正方形なので A＝1） */
function fit(r: Rect, vw: number, vh: number, A = vw / vh): Rect {
  let w = r.w + PAD * 2, h = r.h + PAD * 2;
  if (w / h < A) w = h * A; else h = w / A;
  if (w < vw / MAX_ZOOM) { w = vw / MAX_ZOOM; h = w / A; }
  const maxW = Math.min(vw, vh * A);   // 録画の外は映さない
  if (w > maxW) { w = maxW; h = w / A; }
  const cx = r.x + r.w / 2, cy = r.y + r.h / 2;
  return { x: Math.min(Math.max(cx - w / 2, 0), vw - w), y: Math.min(Math.max(cy - h / 2, 0), vh - h), w, h };
}
const mix = (a: number, b: number, t: number) => a + (b - a) * t;

/** 縦の動画の「映す範囲」。箱（正方形）に横長の四角を丸ごと入れると字が読めないので、横は KEEP の割合まで削って寄り、
 *  削った分はカーソルを追って動かす（rx0〜rx1 がカメラの左端の動ける範囲）。寄るのは録画の倍率で字がぼやけない所（minW）まで */
type CamR = Rect & { rx0: number; rx1: number };
const KEEP = 0.75;
function fitFollow(r: Rect, vw: number, vh: number, A: number, minW: number): CamR {
  const w0 = r.w + PAD * 2, h0 = r.h + PAD * 2;
  let h = Math.max(h0, (w0 * KEEP) / A), w = h * A;
  if (w < minW) { w = minW; h = w / A; }
  const maxW = Math.min(vw, vh * A);
  if (w > maxW) { w = maxW; h = w / A; }
  const clampX = (x: number) => Math.min(Math.max(x, 0), vw - w);
  const y = Math.min(Math.max(r.y + r.h / 2 - h / 2, 0), vh - h);
  if (w >= w0) { const x = clampX(r.x + r.w / 2 - w / 2); return { x, y, w, h, rx0: x, rx1: x }; }
  const rx0 = clampX(r.x - PAD), rx1 = clampX(r.x + r.w + PAD - w);
  return { x: (rx0 + rx1) / 2, y, w, h, rx0, rx1 };
}

/** 「from から to へ dur コマで移る」を印の順に重ねて、f コマ目の値を出す（移る途中で次の印が来たら、その時点の値から移り直す） */
function track<T>(marks: { f: number; to: T; dur: number }[], f: number, lerp: (a: T, b: T, t: number) => T): T {
  let seg = { from: marks[0].to, to: marks[0].to, f0: 0, dur: 0 };
  const at = (s: typeof seg, x: number) => s.dur <= 0 ? s.to : lerp(s.from, s.to, ease(Math.min(1, Math.max(0, (x - s.f0) / s.dur))));
  for (const m of marks.slice(1)) {
    if (m.f > f) break;
    seg = { from: at(seg, m.f), to: m.to, f0: m.f, dur: m.dur };
  }
  return at(seg, f);
}

const Arrow: React.FC<{ size: number; tilt: boolean }> = ({ size, tilt }) => (
  <svg width={22 * size} height={30 * size} viewBox="0 0 22 30"
       style={{ position: "absolute", left: -2 * size, top: -1 * size, transformOrigin: `${2 * size}px ${1 * size}px`,
                transform: tilt ? "rotate(-12deg)" : undefined, filter: `drop-shadow(${size}px ${2 * size}px 0 rgba(0,0,0,.35))` }}>
    <path d="M2 1 L2 22 L7.5 17 L11 25.5 L15 24 L11.5 15.5 L19 15 Z" fill="#fff" stroke="#111" strokeWidth={2} strokeLinejoin="round" />
  </svg>
);

/** Playwright のキーの名前 → キーの絵に書く字（Mac の人もいるので Ctrl と ⌘ は併記しない。投稿の本文で補う） */
const KEY_LABEL: Record<string, string> = { Control: "Ctrl", Alt: "Alt", Shift: "Shift", Meta: "⌘", ArrowRight: "→", ArrowLeft: "←", ArrowUp: "↑", ArrowDown: "↓", Enter: "Return", Escape: "Esc", Tab: "Tab" };
const KEY_SHOW = 20;   // キーの絵を出しておくコマ数

/** 押したキーの絵（画面の下の真ん中）。次のキーが来たら入れ替わる。押した直後の数コマは沈んで見せる */
const Keys: React.FC<{ events: Ev[]; f: number; unit: number }> = ({ events, f, unit }) => {
  const e = [...events].reverse().find((x): x is Extract<Ev, { type: "key" }> => x.type === "key" && x.f <= f);
  if (!e || f >= e.f + KEY_SHOW) return null;
  const age = f - e.f, down = age < 4;
  const opacity = interpolate(age, [KEY_SHOW - 5, KEY_SHOW], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const u = unit, sh = down ? 1 : 4;
  return (
    // **白い台に載せる**（画面の上にじかに置くと、後ろのボタンの字と「+」が重なって読めない）
    <div style={{ position: "absolute", left: 0, right: 0, bottom: 32 * u, display: "flex", justifyContent: "center", opacity }}>
      <div style={{ display: "flex", gap: 12 * u, alignItems: "center", background: "#fff", border: `${2 * u}px solid #111`,
                    boxShadow: `${5 * u}px ${5 * u}px 0 #111`, padding: `${12 * u}px ${16 * u}px` }}>
        {e.key.split("+").map((k, i) => (
          <React.Fragment key={i}>
            {i > 0 && <span style={{ fontFamily: "XKey", fontSize: 40 * u, color: "#111" }}>+</span>}
            <span style={{ fontFamily: "XKey", fontSize: 40 * u, lineHeight: 1, color: "#111", background: "#e4e4e4", border: `${2 * u}px solid #111`,
                           padding: `${10 * u}px ${18 * u}px`, minWidth: 72 * u, textAlign: "center",
                           boxShadow: `${sh * u}px ${sh * u}px 0 #111`, transform: `translate(${(4 - sh) * u}px, ${(4 - sh) * u}px)` }}>
              {KEY_LABEL[k] ?? k.toUpperCase()}
            </span>
          </React.Fragment>
        ))}
      </div>
    </div>
  );
};

/** 指の印（スマホの場面。矢印の代わりに半透明の丸。押している間は濃く・小さく） */
const Finger: React.FC<{ r: number; pressing: boolean }> = ({ r, pressing }) => {
  const rr = pressing ? r * 0.85 : r;
  return <div style={{ position: "absolute", left: -rr, top: -rr, width: rr * 2, height: rr * 2, borderRadius: "50%",
                       background: pressing ? "rgba(20,20,20,.45)" : "rgba(20,20,20,.25)", border: "2px solid rgba(255,255,255,.85)", boxSizing: "border-box" }} />;
};

/** 1 コマぶんの絵。**スマホの場面**（録画が縦長）は、16:9 の真ん中にスマホの枠を置いてその中に映す（2026-09-26、利用者の決定） */
const Scene: React.FC<{ id: string; take: Take; title?: string; phoneMode?: "frame" | "fill" }> = ({ id, take, title, phoneMode }) => {
  const { width, height } = useVideoConfig();
  if (height > width) return <TallScene id={id} take={take} title={title} phoneMode={phoneMode} />;
  if (take.vh <= take.vw) {
    return (
      <AbsoluteFill style={{ backgroundColor: "#000", overflow: "hidden" }}>
        <View id={id} take={take} w={width} h={height} touch={false} />
        <Keys events={take.events} f={useCurrentFrame()} unit={width / 1280} />
      </AbsoluteFill>
    );
  }
  const H = Math.round(height * 0.88), W = Math.round(H * take.vw / take.vh), bez = Math.round(H * 0.022);
  // 2 台のときは左右に並べる（右は 2 台目の録画。指の印とカメラは付けない）
  const gap = Math.round(W * 0.35), n = take.twin ? 2 : 1;
  const x0 = Math.round((width - (W * n + gap * (n - 1))) / 2), y = Math.round((height - H) / 2);
  const phone = (x: number, body: React.ReactNode, key: string) => (
    <React.Fragment key={key}>
      <div style={{ position: "absolute", left: x - bez, top: y - bez * 2, width: W + bez * 2, height: H + bez * 4, background: "#16181b",
                    borderRadius: bez * 3.2, boxShadow: `${bez}px ${bez}px 0 rgba(0,0,0,.18)` }} />
      <div style={{ position: "absolute", left: x, top: y, width: W, height: H, overflow: "hidden", borderRadius: bez * 1.2, background: "#fff" }}>{body}</div>
    </React.Fragment>
  );
  return (
    // 地はサイトの机の色（ごく薄い灰色）。枠は角の丸い黒（スマホの本体。サイトの部品ではないので角丸でよい）
    <AbsoluteFill style={{ backgroundColor: "#e9e8e3" }}>
      {phone(x0, <View id={id} take={take} w={W} h={H} touch />, "a")}
      {take.twin && phone(x0 + W + gap, <View id={id} take={{ ...take, events: [] }} w={W} h={H} touch src="take2.mp4" />, "b")}
    </AbsoluteFill>
  );
};

/** 縦 9:16（Instagram のリール・TikTok 向け、2026-09-27）。上に見出し（/howto の問い）、真ん中に OS 9 風の窓で録画。
 *  PC の録画は 16:9 のまま縦に置くと字が読めないので、窓の中身を正方形にして印の四角に寄る。スマホの録画は枠ごと大きく置く。
 *  下の 2 割と右端はアプリの字幕・ボタンが重なるので、大事なものを置かない */
const TALL = { ink: "#1b1d24", desk: "#e9e8e3", stripe: ["#e6b731", "#008bc7", "#e5462c", "#af9ee4", "#80e2b9", "#f594c3"] };
const TallScene: React.FC<{ id: string; take: Take; title?: string; phoneMode?: "frame" | "fill" }> = ({ id, take, title, phoneMode = "frame" }) => {
  const { width } = useVideoConfig();
  const f = useCurrentFrame();
  const head = (
    <div style={{ position: "absolute", left: 80, right: 80, top: 250 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <div style={{ fontFamily: "XMark", fontWeight: 700, fontSize: 34, letterSpacing: "0.06em", color: TALL.ink, lineHeight: 1 }}>TRACKMENTO</div>
        <div style={{ display: "flex", flex: 1, height: 12 }}>{TALL.stripe.map((c) => <div key={c} style={{ flex: 1, background: c }} />)}</div>
      </div>
      {title && <div lang="ja" style={{ wordBreak: "auto-phrase" as React.CSSProperties["wordBreak"], marginTop: 28, fontFamily: "XPlex", fontWeight: 700, fontSize: 62, lineHeight: 1.36, color: TALL.ink }}>{title}</div>}
    </div>
  );
  if (take.vh > take.vw && phoneMode === "fill" && !take.twin) {
    // B 案: スマホの画面を幅いっぱいに寄せ、縦は指を追う（枠は描かない。見出しの下から画面の下まで）
    const top = 560;
    return (
      <AbsoluteFill style={{ backgroundColor: TALL.desk }}>
        {head}
        <div style={{ position: "absolute", left: 0, top, width, height: 1920 - top, overflow: "hidden", background: "#fff", borderTop: `4px solid ${TALL.ink}` }}>
          <View id={id} take={take} w={width} h={1920 - top} touch followY />
        </div>
      </AbsoluteFill>
    );
  }
  if (take.vh > take.vw) {
    const n = take.twin ? 2 : 1, H = n === 2 ? 940 : 1100, W = Math.round(H * take.vw / take.vh), bez = 22, gap = 56;
    const x0 = Math.round((width - (W * n + gap * (n - 1))) / 2), y = 610;
    const phone = (x: number, body: React.ReactNode, key: string) => (
      <React.Fragment key={key}>
        <div style={{ position: "absolute", left: x - bez, top: y - bez * 2, width: W + bez * 2, height: H + bez * 4, background: "#16181b",
                      borderRadius: bez * 3.2, boxShadow: `${bez}px ${bez}px 0 rgba(0,0,0,.18)` }} />
        <div style={{ position: "absolute", left: x, top: y, width: W, height: H, overflow: "hidden", borderRadius: bez * 1.2, background: "#fff" }}>{body}</div>
      </React.Fragment>
    );
    return (
      <AbsoluteFill style={{ backgroundColor: TALL.desk }}>
        {head}
        {phone(x0, <View id={id} take={take} w={W} h={H} touch />, "a")}
        {take.twin && phone(x0 + W + gap, <View id={id} take={{ ...take, events: [] }} w={W} h={H} touch src="take2.mp4" />, "b")}
      </AbsoluteFill>
    );
  }
  // 窓の中身の高さは、寄る四角でいちばん横長なものに合わせる（正方形のままだと横長の場面で下半分が空く）。幅は 920 で固定
  // 窓の中身は正方形。横長の場面は fitFollow で寄ってカーソルを追う
  const S = 920, SH = 920, bar = 44, x = (width - S) / 2, y = 600;
  return (
    <AbsoluteFill style={{ backgroundColor: TALL.desk }}>
      {head}
      {/* 窓（OS 9 のプラチナ風。角丸なし・影は真っ黒を右下へ・題名バーは縞） */}
      <div style={{ position: "absolute", left: x - 4, top: y - 4, width: S + 8, height: bar + SH + 8, background: TALL.ink, boxShadow: `12px 12px 0 ${TALL.ink}` }} />
      <div style={{ position: "absolute", left: x, top: y, width: S, height: bar, background: "#dcdcdc", display: "flex", alignItems: "center", justifyContent: "center",
                    backgroundImage: `repeating-linear-gradient(#dcdcdc 0 6px, #8a8a8a 6px 8px)`, backgroundClip: "content-box", padding: "8px 12px", boxSizing: "border-box" }}>
        <span style={{ background: "#dcdcdc", padding: "0 16px", fontFamily: "XSilk", fontSize: 26, color: TALL.ink, lineHeight: 1 }}>trackmento.com</span>
      </div>
      <div style={{ position: "absolute", left: x, top: y + bar, width: S, height: SH, overflow: "hidden", background: "#fff" }}>
        <View id={id} take={take} w={S} h={SH} touch={false} follow />
        <Keys events={take.events} f={f} unit={S / 1280 * 1.15} />
      </div>
    </AbsoluteFill>
  );
};

/** 録画＋カメラ＋カーソル（指）＋輪を w×h の箱に描く */
const View: React.FC<{ id: string; take: Take; w: number; h: number; touch: boolean; src?: string; follow?: boolean; followY?: boolean }> = ({ id, take, w: width, h: height, touch, src = "take.mp4", follow = false, followY = false }) => {
  const f = useCurrentFrame();
  const { vw, vh, events } = take;
  const k = width / vw;   // 出力の px ÷ 画面の CSS px（引いたとき）
  const A = width / height;

  const curs = events.filter((e): e is Extract<Ev, { type: "cursor" }> => e.type === "cursor").map((e) => ({ f: e.f, to: { x: e.x, y: e.y }, dur: e.dur }));
  const camEvs = events.filter((e): e is Extract<Ev, { type: "cam" }> => e.type === "cam");
  const lerpCam = (a: CamR, b: CamR, t: number): CamR => ({ x: mix(a.x, b.x, t), y: mix(a.y, b.y, t), w: mix(a.w, b.w, t), h: mix(a.h, b.h, t), rx0: mix(a.rx0, b.rx0, t), rx1: mix(a.rx1, b.rx1, t) });
  const place = (r: Rect): CamR => follow ? fitFollow(r, vw, vh, A, width / take.dpr) : { ...fit(r, vw, vh, A), rx0: NaN, rx1: NaN };
  const cams = camEvs.map((e) => ({ f: e.f, to: place(e.rect), dur: e.dur }));
  const cam = cams.length ? track(cams, f, lerpCam) : place({ x: 0, y: 0, w: vw, h: vh });
  if (followY) {
    // 幅はいつも画面ぜんぶ。縦は指の位置（前後 0.5 秒の平均）が箱の上から 45% に来るように送る。指が無いときは印の四角の真ん中
    const w = vw, h = w / A;
    let ty = cam.y + cam.h / 2;
    if (curs.length) {
      let sy = 0, n = 0;
      for (let d = -15; d <= 15; d += 3) { sy += track(curs, Math.max(0, f + d), (a, b, t) => ({ x: mix(a.x, b.x, t), y: mix(a.y, b.y, t) })).y; n++; }
      ty = sy / n + h * 0.05;
    }
    Object.assign(cam, { x: 0, w, h, y: Math.min(Math.max(ty - h / 2, 0), vh - h) });
  }
  if (follow && cam.rx1 > cam.rx0 && curs.length) {
    // 横はカーソルを追う（前後 0.5 秒の平均。少し先を見て動き出すので、押す前に押す所が映る）
    let sx = 0, n = 0;
    for (let d = -15; d <= 15; d += 3) { sx += track(curs, Math.max(0, f + d), (a, b, t) => ({ x: mix(a.x, b.x, t), y: mix(a.y, b.y, t) })).x; n++; }
    cam.x = Math.min(Math.max(sx / n - cam.w / 2, cam.rx0), cam.rx1);
  }
  const s = (vw / cam.w) * k;   // 画面の CSS px → 出力の px
  const toScreen = (x: number, y: number) => ({ x: (x - cam.x) * s, y: (y - cam.y) * s });

  const lastVis = [...events].reverse().find((e) => e.f <= f && (e.type === "cursor" || e.type === "hide"));
  const showCursor = curs.length > 0 && lastVis?.type === "cursor";
  const cp = showCursor ? track(curs, f, (a, b, t) => ({ x: mix(a.x, b.x, t), y: mix(a.y, b.y, t) })) : null;
  const downs = events.filter((e): e is Extract<Ev, { type: "down" }> => e.type === "down");
  const pressing = downs.some((d) => f >= d.f && f < d.f + 6);
  // 矢印の大きさは寄った倍率に合わせる（画面の部品と釣り合うように。引いたときでも小さくなりすぎないよう下限あり）
  const size = Math.max(1.3, s * 0.9);

  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <OffthreadVideo src={staticFile(`xclips/${id}/${src}`)} muted
        style={{ position: "absolute", left: 0, top: 0, width: vw * k, height: vh * k, transformOrigin: "0 0",
                 transform: `translate(${-cam.x * s}px, ${-cam.y * s}px) scale(${vw / cam.w})` }} />
      {downs.filter((d) => d.ring !== false && f >= d.f && f < d.f + 14).map((d, i) => {
        const p = toScreen(d.x, d.y), age = (f - d.f) / 14;
        const r = interpolate(age, [0, 1], [6, 30]) * Math.max(1, s * 0.8);
        return <div key={i} style={{ position: "absolute", left: p.x - r, top: p.y - r, width: r * 2, height: r * 2, borderRadius: "50%",
                                     border: `${3 * Math.max(1, s * 0.7)}px solid #e5462c`, opacity: 1 - age, boxSizing: "border-box" }} />;
      })}
      {(() => {
        // 2 本指（pinch）。いちばん新しい印の位置に指の丸を置く（押している濃さ）
        const t = [...events].reverse().find((e): e is Extract<Ev, { type: "touches" }> => e.type === "touches" && e.f <= f);
        return t?.pts.map((q, i) => { const p = toScreen(q.x, q.y); return <div key={`t${i}`} style={{ position: "absolute", left: p.x, top: p.y }}><Finger r={18 * s} pressing /></div>; });
      })()}
      {cp && (() => { const p = toScreen(cp.x, cp.y); return <div style={{ position: "absolute", left: p.x, top: p.y }}>
        {touch ? <Finger r={18 * s} pressing={pressing} /> : <Arrow size={size} tilt={pressing} />}</div>; })()}
    </AbsoluteFill>
  );
};

export const XClip: React.FC<XClipProps> = ({ id, take, title, phoneMode }) => {
  const f = useCurrentFrame();
  if (!take) return null;
  const N = take.frames;
  const fade = interpolate(f, [N, N + LOOP], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });
  return (
    <AbsoluteFill>
      <Freeze frame={N - 1} active={f >= N}><Scene id={id} take={take} title={title} phoneMode={phoneMode} /></Freeze>
      {f >= N && <AbsoluteFill style={{ opacity: fade }}><Freeze frame={0}><Scene id={id} take={take} title={title} phoneMode={phoneMode} /></Freeze></AbsoluteFill>}
    </AbsoluteFill>
  );
};

/** 長さは素材のコマ数＋つなぎ。events.json を読んで props に入れる（描くたびに読み直さないように） */
export const xclipMetadata: CalculateMetadataFunction<XClipProps> = async ({ props }) => {
  const take: Take = await (await fetch(staticFile(`xclips/${props.id}/events.json`))).json();
  // 縦の動画の見出し（promo/x_titles.py が書く。横では使わない）
  const titles: Record<string, Record<string, string>> = await fetch(staticFile("xclips-titles.json")).then((r) => r.ok ? r.json() : {}).catch(() => ({}));
  const title = props.title ?? (titles[props.id] ?? titles[props.id.replace(/-sp$/, "")])?.[props.lang ?? "ja"];   // スマホ版（-sp）は元の場面の見出し
  return { durationInFrames: take.frames + LOOP, fps: take.fps, props: { ...props, take, title } };
};
