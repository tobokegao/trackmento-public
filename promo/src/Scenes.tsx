// TRACKMENTO 紹介動画。9:16（tall）と 16:9（wide）を同じ部品・同じ拍割りで描く。拍割りは timeline.ts
import React from "react";
import {
  AbsoluteFill, Audio, Freeze, Img, OffthreadVideo, Sequence, interpolate, spring, measureSpring, staticFile, useCurrentFrame, useVideoConfig, Easing,
} from "remotion";
import { loadFont } from "@remotion/fonts";
import {
  FPS, BAR, beatTime, beatFrame, sec, evTime, evRect, evRects, rate, RECORDINGS, SHOTS, SITES, SITES_EN, POINTS, Shot, Kind, Lang,
  INTRO_END, HOOK_BEAT, POINTS_BEAT, SHOWCASE_BEAT, TAIL_BEAT, TAIL_SHOTS, END_BEAT, URL_BEAT, FREE_BEAT, LAST_BEAT, FADE_FROM,
} from "./timeline";

// ---- フォント（アプリと同じ OFL 同梱フォント） ----
loadFont({ family: "Plex", url: staticFile("fonts/IBMPlexSansJP-Bold.ttf"), weight: "700" });
loadFont({ family: "Plex", url: staticFile("fonts/IBMPlexSansJP-Regular.ttf"), weight: "400" });
loadFont({ family: "Silk", url: staticFile("fonts/Silkscreen-Bold.ttf"), weight: "700" });
loadFont({ family: "Mark", url: staticFile("fonts/TrackmentoMark-Bold.ttf"), weight: "700" });
loadFont({ family: "Mark", url: staticFile("fonts/TrackmentoMark-Bold.ttf"), weight: "400" });   // 細字の指定でも同じ字（M が H に見えないように。v8）   // ロゴ専用（M だけ描き替えた Silkscreen。scripts/build_logo_font.py）
loadFont({ family: "Dot", url: staticFile("fonts/DotGothic16-Regular.ttf"), weight: "400" });

// ---- 色（frontend/index.html のトークンと同じ系統） ----
export const C = {
  paper: "#f5f4f0", ink: "#1b1d24", muted: "#5a5e6a",
  mustard: "#e6b731", cerulean: "#008bc7", vermilion: "#e5462c", lavender: "#af9ee4", mint: "#80e2b9", pink: "#f594c3",
};
const STRIPE = [C.mustard, C.cerulean, C.vermilion, C.lavender, C.mint, C.pink];

// ---- レイアウト ----
export type LayoutKind = "tall" | "wide";
type Layout = {
  lang: Lang;                                                 // 画面も字幕もこの言語で出す
  kind: LayoutKind; W: number; H: number;
  phone: { x: number; y: number; w: number; h: number };      // 録画を入れる枠
  jp: number; en: number;                                     // 字幕サイズ
  mark: number; tag: number; sub: number;                     // ワードマーク・見出し・小さめ文字
};
const LAYOUTS: Record<LayoutKind, Omit<Layout, "lang">> = {
  tall: { kind: "tall", W: 1080, H: 1920, phone: { x: 108, y: 330, w: 864, h: 1536 }, jp: 62, en: 36, mark: 102, tag: 64, sub: 40 },
  wide: { kind: "wide", W: 1920, H: 1080, phone: { x: 222, y: 215, w: 1476, h: 830 }, jp: 60, en: 34, mark: 140, tag: 60, sub: 38 },
};

/** 直前の拍からの経過で減衰するパルス。拍の頭で 1 */
function useBeatPulse(decayBeats = 1) {
  const frame = useCurrentFrame();
  const t = frame / FPS;
  let last = -1;
  for (let i = 0; i < 400; i++) { if (beatTime(i) <= t) last = i; else break; }
  if (last < 0) return { pulse: 0, beat: -1 };
  const len = (beatTime(last + 1) - beatTime(last)) * decayBeats;
  const p = Math.max(0, 1 - (t - beatTime(last)) / len);
  return { pulse: p * p, beat: last };
}

const Paper: React.FC<{ children?: React.ReactNode }> = ({ children }) => (
  <AbsoluteFill style={{ background: C.paper }}>
    <AbsoluteFill style={{ backgroundImage: `radial-gradient(${C.ink}12 1.2px, transparent 1.3px)`, backgroundSize: "14px 14px", opacity: 0.9 }} />
    {children}
  </AbsoluteFill>
);

/** 6 色の帯。拍ごとに 1 色ずつ跳ねる */
// lead … ロゴの下線だけ、頭に離して小さな四角を置く（画面・リンクカードと同じ形。四角は線の太さの 0.88 倍、すき間 0.35 倍）
const Stripe: React.FC<{ h?: number; width?: number | string; lead?: boolean }> = ({ h = 14, width = "100%", lead = false }) => {
  const { beat, pulse } = useBeatPulse();
  return (
    <div style={{ width, height: h, display: "flex", position: "relative" }}>
      {lead && <div style={{ position: "absolute", top: 0, bottom: 0, width: Math.round(h * 0.88), right: `calc(100% + ${Math.round(h * 0.35)}px)`, background: STRIPE[0] }} />}
      {STRIPE.map((c, i) => <div key={c} style={{ flex: 1, background: c, transform: `scaleY(${beat >= 0 && beat % 6 === i ? 1 + pulse * 1.6 : 1})`, transformOrigin: "bottom" }} />)}
    </div>
  );
};

const Wordmark: React.FC<{ size: number }> = ({ size }) => (
  <div style={{ fontFamily: "Mark", fontWeight: 700, fontSize: size, letterSpacing: "0.06em", color: C.ink, lineHeight: 1 }}>TRACKMENTO</div>
);

// ---- イントロ（2 小節で完了） ----
const Intro: React.FC<{ L: Layout }> = ({ L }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const letters = "TRACKMENTO".split("");
  // ロゴは最初の拍の頭（音の出だし）から 1 拍以内に全文字。帯はロゴと一緒に。タグラインは 2 小節目の頭で
  const beat0 = beatFrame(0), beatLen = beatFrame(1) - beatFrame(0);
  const logoIn = spring({ frame: frame - beat0, fps, config: { damping: 14, stiffness: 200 } });
  const taglineIn = spring({ frame: frame - beatFrame(BAR), fps, config: { damping: 14, stiffness: 140 } });
  const out = interpolate(frame, [beatFrame(INTRO_END) - 8, beatFrame(INTRO_END)], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.in(Easing.cubic) });
  const stripeW = L.kind === "tall" ? 1000 : 1400;
  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", transform: `translateY(${-out * 600}px)`, opacity: 1 - out }}>
      <div style={{ display: "flex", gap: L.kind === "tall" ? 6 : 8 }}>
        {letters.map((ch, i) => {
          const s = spring({ frame: frame - beat0 - Math.round((i / letters.length) * beatLen * 0.35), fps, config: { damping: 14, stiffness: 420 } });   // 全文字が 1 拍以内に出る
          return <span key={i} style={{ fontFamily: "Mark", fontWeight: 700, fontSize: L.kind === "tall" ? 106 : 150, color: C.ink, lineHeight: 1, display: "inline-block", transform: `translateY(${(1 - s) * 60}px)`, opacity: s }}>{ch}</span>;
        })}
      </div>
      <div style={{ marginTop: 24, opacity: logoIn, transform: `scaleX(${logoIn})` }}><Stripe h={18} lead width={stripeW} /></div>
      <div style={{ marginTop: L.kind === "tall" ? 80 : 56, textAlign: "center", transform: `translateY(${(1 - taglineIn) * 40}px)`, opacity: taglineIn }}>
        {L.lang === "ja" ? (
          <>
            <div style={{ fontFamily: "Plex", fontWeight: 700, fontSize: L.tag, color: C.ink, lineHeight: 1.3 }}>
              {L.kind === "tall" ? <>好きな曲で、<br />ジャケットのグリッドを。</> : "好きな曲で、ジャケットのグリッドを。"}
            </div>
            <div style={{ fontFamily: "Dot", fontSize: L.sub, color: C.muted, marginTop: 20, letterSpacing: "0.04em" }}>Your tracks. One grid.</div>
          </>
        ) : (
          <div style={{ fontFamily: "Dot", fontSize: L.tag, color: C.ink, letterSpacing: "0.04em", lineHeight: 1.3 }}>Your tracks. One grid.</div>
        )}
      </div>
    </AbsoluteFill>
  );
};

// ---- 字幕（上段 日本語・下段 英語） ----
const Caption: React.FC<{ L: Layout; jp: string; en: string; children?: React.ReactNode; delay?: number; still?: boolean }> = ({ L, jp, en, children, delay = 0, still }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = still ? 1 : spring({ frame: frame - delay, fps, config: { damping: 12, stiffness: 170 } });
  if (frame < delay) return null;
  // 日本語版は日本語を主役に英語を添える。英語版は英語だけ（添えるものが無い）
  const head = L.lang === "ja" ? jp : en;
  const sub = L.lang === "ja" ? en : "";
  const slide = `translateX(${(1 - s) * -40}px)`;
  const box = L.kind === "tall"
    ? { position: "absolute" as const, left: 60, right: 60, top: 70, display: "flex", flexDirection: "column" as const, alignItems: "flex-start" }
    : { position: "absolute" as const, left: 222, right: 222, top: 36, display: "flex", flexDirection: "column" as const, alignItems: "flex-start" };
  const tall = L.kind === "tall";
  return (
    <div style={{ ...box, flexDirection: tall ? "column" : "row", alignItems: tall ? "flex-start" : "flex-end", gap: tall ? 0 : 40 }}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
        {head && <div style={{ background: C.ink, color: C.paper, fontFamily: L.lang === "ja" ? "Plex" : "Dot", fontWeight: 700, fontSize: L.lang === "ja" ? L.jp : L.jp * 0.82, lineHeight: 1.15, padding: tall ? "10px 26px" : "12px 34px", whiteSpace: "pre-line", transform: slide, opacity: s }}>{head}</div>}
        {sub && <div style={{ fontFamily: "Dot", fontSize: L.en, color: C.muted, marginTop: 14, letterSpacing: "0.03em", transform: slide, opacity: s }}>{sub}</div>}
      </div>
      {children}
    </div>
  );
};

/** URL 対応サイトを 8 分音符 3 連（1 拍に 3 つ）で並べる */
const SiteBadges: React.FC<{ L: Layout; startBeat: number }> = ({ L, startBeat }) => {
  const sites = L.lang === "ja" ? SITES : SITES_EN;
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const step = (beatTime(startBeat + 1) - beatTime(startBeat)) / 3;
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: L.kind === "tall" ? 16 : 0, marginBottom: L.kind === "tall" ? 0 : 6, maxWidth: L.kind === "tall" ? 960 : 1000 }}>
      {sites.map((name, i) => {
        const at = Math.round(step * i * fps);   // Sequence 内の相対フレーム
        const s = spring({ frame: frame - at, fps, config: { damping: 9, stiffness: 260 } });
        // Apple Music だけはクリーム地に黒文字（本家の見た目に寄せる）
        const bg = name === "Apple Music" ? C.paper : STRIPE[i % 6];
        return <span key={name} style={{ fontFamily: "Plex", fontWeight: 700, fontSize: L.kind === "tall" ? 23 : 26, color: C.ink, border: `3px solid ${C.ink}`, background: bg, padding: "2px 10px", display: "inline-block", transform: `scale(${s})`, opacity: s }}>{name}</span>;
      })}
    </div>
  );
};

/** シーン冒頭 1 拍: 16 分音符で画面全体を反転→通常に 2 往復 */
const FlashIn: React.FC = () => {
  const frame = useCurrentFrame();
  const sixteenth = (beatFrame(BAR) - beatFrame(0)) / 16;
  const k = Math.floor(frame / sixteenth);
  if (!(k < 4 && k % 2 === 0)) return null;
  return <AbsoluteFill style={{ background: "#fff", mixBlendMode: "difference", pointerEvents: "none" }} />;
};

/** スマホ枠。子に録画（OffthreadVideo）を入れる。fx でシーン末尾の演出 */
const Phone: React.FC<{ L: Layout; fx?: Shot["fx"]; children: React.ReactNode }> = ({ L, fx, children }) => {
  const frame = useCurrentFrame();
  const { pulse } = useBeatPulse(0.6);
  const barFrames = beatFrame(BAR) - beatFrame(0);
  const sixteenth = barFrames / 16;
  let tx = 0, ty = 0, sc = 1, filter = "none";
  if (fx === "glitchOut") {
    // 末尾 1 小節: 16 分音符 12 拍目で右上へ瞬時移動して拡大（見切れるほど）、14 拍目で左下へ瞬時移動して縮小、16 拍目で中央へ
    const k = Math.floor(frame / sixteenth), f = (frame - k * sixteenth) / sixteenth;   // k: 0 始まりの 16 分音符番号、f: その中の進み
    const dx = L.phone.w * 0.32, dy = L.phone.h * 0.3;
    if (k === 11) { tx = dx; ty = -dy; sc = 1 + 0.6 * Math.min(1, f * 1.15); }
    else if (k === 12) { tx = dx; ty = -dy; sc = 1.6; }
    else if (k === 13) { tx = -dx; ty = dy; sc = 1.6 - 1.1 * Math.min(1, f * 1.15); }
    else if (k === 14) { tx = -dx; ty = dy; sc = 0.5; }
    else if (k >= 15) { tx = 0; ty = 0; sc = 1; }
  }
  return (
    <div style={{ position: "absolute", left: L.phone.x, top: L.phone.y, width: L.phone.w, height: L.phone.h, border: `${L.kind === "tall" ? 6 : 5}px solid ${C.ink}`, boxShadow: `${L.kind === "tall" ? 14 : 12}px ${L.kind === "tall" ? 14 : 12}px 0 ${C.ink}`, background: C.paper, overflow: "hidden", transform: `translate(${tx}px, ${ty}px) scale(${sc * (1 + pulse * 0.012)})`, transformOrigin: "50% 45%", filter }}>
      {children}
    </div>
  );
};

/** 録画の一部を枠線で強調（拍で脈打つ） */
const Highlight: React.FC<{ L: Layout; hl: NonNullable<Shot["hl"]>; clipScale?: number }> = ({ L, hl, clipScale = 1.03 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { pulse } = useBeatPulse(0.8);
  const s = spring({ frame, fps, config: { damping: 12, stiffness: 160 } });
  const pad = 6 + pulse * 6;
  // 枠を対象の外へ広げるぶん（録画の実寸で 22px 相当）。縦横で見た目が同じになるよう別々に出す
  const padX = 22 / L.phone.w, padY = 22 / L.phone.h;
  // 中心を軸に clipScale 倍した位置に置き、**録画の枠からはみ出さないように止める**
  // （そのままだと右端や下端が画面の外に出て、枠線が切れたり端の飾りと重なって見える）
  const at = (v: number) => 0.5 + (v - 0.5) * clipScale;
  const x0 = Math.max(0.008, at(hl.x - padX)), x1 = Math.min(0.992, at(hl.x + hl.w + padX));
  // 上下は hl.pt / hl.pb（録画の縦 1920px での px）で個別に決められる。枠線（8px）が文字やボタンに
  // かからないよう、上下のすきまに収まる値を測って入れる
  const pt = hl.pt !== undefined ? hl.pt / 1920 : padY, pb = hl.pb !== undefined ? hl.pb / 1920 : padY;
  const y0 = Math.max(0.008, at(hl.y - pt)), y1 = Math.min(0.992, at(hl.y + hl.h + pb));
  return (
    <div style={{ position: "absolute",
      // 録画は Clip が中心を軸に clipScale 倍している。枠も同じだけ動かさないと対象からずれる。
      // そのうえで対象の外側に少し余裕を持たせる（ぴったりだと窮屈に見える）
      left: `${x0 * 100}%`, top: `${y0 * 100}%`,
      width: `${(x1 - x0) * 100}%`, height: `${(y1 - y0) * 100}%`, boxSizing: "border-box",
      border: `8px solid ${C.vermilion}`, boxShadow: `0 0 0 ${pad}px ${C.vermilion}55`, transform: `scale(${0.9 + s * 0.1})`, opacity: s, pointerEvents: "none" }} />
  );
};

/** カメラの 1 点（録画の時刻 t 秒に、画面の割合 (x, y) を中心に s 倍で見る） */
type CamKey = { t: number; x: number; y: number; s: number };
/** 印の四角からカメラの点を作る。四角を 1.5 倍に広げ、画面の 45% より小さくはしない（寄りすぎない）。倍率は 1〜2 倍 */
const camKey = (t: number, r: { x: number; y: number; w: number; h: number }): CamKey => {
  const w = Math.max(r.w * 1.5, 0.45), h = Math.max(r.h * 1.5, 0.45);
  return { t, x: r.x + r.w / 2, y: r.y + r.h / 2, s: Math.max(1, Math.min(2, 1 / w, 1 / h)) };
};
/** 横の録画のカメラ（2026-09-22、利用者の指摘）。**操作した場所（押したボタン・打った欄）を順に追って寄る**。
    以前は場面ごとに手で決めた寄り先（zoomPc）で、スクロール位置が変わると操作と関係ない所を映していた。
    ショットの頭より前の最後の操作から始め（「入力欄の場所から」始まる）、次の操作の少し前（LEAD）から動き出して間に合わせる */
const CAM_LEAD = 0.35, CAM_MOVE = 0.45;   // 録画の秒
function camAt(keys: CamKey[], vt: number): CamKey | null {
  if (!keys.length) return null;
  let i = -1;
  for (let k = 0; k < keys.length; k++) if (keys[k].t <= vt + CAM_LEAD) i = k;
  if (i < 0) return keys[0];
  const cur = keys[i], prev = keys[Math.max(0, i - 1)];
  const p = Easing.inOut(Easing.cubic)(Math.max(0, Math.min(1, (vt + CAM_LEAD - cur.t) / CAM_MOVE)));
  return { t: vt, x: prev.x + (cur.x - prev.x) * p, y: prev.y + (cur.y - prev.y) * p, s: prev.s + (cur.s - prev.s) * p };
}
const Clip: React.FC<{ kind: Kind; lang: Lang; session: "main" | "feat"; from: number; speed?: number; zoom?: Shot["zoom"]; still?: boolean; cam?: CamKey[] }> = ({ kind, lang, session, from, speed = 1, zoom, still, cam }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const r = rate(kind, lang, session) * speed;
  const video = <OffthreadVideo src={staticFile(RECORDINGS[kind][lang][session].src)} startFrom={sec(from)} playbackRate={r} muted style={{ width: "100%", height: "100%", objectFit: "cover" }} />;
  const c = cam && !still ? camAt(cam, from + (frame / fps) * r) : null;
  if (c) {
    // 中心 (x, y) を画面の真ん中に持ってくる。端の外が見えないように中心を寄せる
    const s = c.s * 1.03, x = Math.max(0.5 / s, Math.min(1 - 0.5 / s, c.x)), y = Math.max(0.5 / s, Math.min(1 - 0.5 / s, c.y));
    return (
      <div style={{ width: "100%", height: "100%", transform: `translate(${(0.5 - x) * s * 100}%, ${(0.5 - y) * s * 100}%) scale(${s})`, transformOrigin: "50% 50%" }}>
        {video}
      </div>
    );
  }
  const z = zoom ? interpolate(frame, [0, fps * 0.5], [1.03, zoom.s], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) }) : 1.03;
  const origin = zoom ? `${zoom.x * 100}% ${zoom.y * 100}%` : "50% 50%";
  return (
    <div style={{ width: "100%", height: "100%", transform: `scale(${z})`, transformOrigin: origin }}>
      {still ? <Freeze frame={0}>{video}</Freeze> : video}
    </div>
  );
};

/** ファイルが保存された窓。frame 0 = 保存した瞬間。名前は録画の events.json（pal:saved の file）から */
const SavedWindow: React.FC<{ L: Layout; file: string; rowAt?: number; blinkAt?: number; hideAt?: number }> = ({ L, file, rowAt = 8, blinkAt, hideAt }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  if (frame < 0) return null;
  const s = spring({ frame, fps, config: { damping: 13, stiffness: 200 } }) * (hideAt === undefined ? 1 : 1 - spring({ frame: frame - hideAt, fps, config: { damping: 16, stiffness: 260 } }));
  const row = spring({ frame: frame - rowAt, fps, config: { damping: 14, stiffness: 220 } });
  // 選択中の青を 16 分音符で点滅（v7）
  const sixteenth = (beatFrame(1) - beatFrame(0)) / 4;
  const selOn = blinkAt === undefined || frame < blinkAt || Math.floor((frame - blinkAt) / sixteenth) % 2 === 0;
  const tall = L.kind === "tall", ja = L.lang === "ja";
  const fs = tall ? 30 : 24;
  const rows = [["trackmento-私を構成する9選.json", "4 KB"], ["trackmento.jpg", "327 KB"]];
  return (
    <div style={{ position: "absolute", left: "7%", right: "7%", top: tall ? "30%" : "22%", border: `4px solid ${C.ink}`, background: C.paper, boxShadow: `10px 10px 0 ${C.ink}`, transform: `translateY(${(1 - s) * 60}px) scale(${0.9 + s * 0.1})`, opacity: s }}>
      <div style={{ height: tall ? 46 : 38, borderBottom: `3px solid ${C.ink}`, display: "flex", alignItems: "center", justifyContent: "center", background: `repeating-linear-gradient(${C.paper} 0 3px, #b9bec6 3px 6px)`, fontFamily: ja ? "Plex" : "Dot", fontWeight: 700, fontSize: fs * 0.9, color: C.ink }}>
        <span style={{ background: C.paper, padding: "0 16px" }}>{ja ? "ダウンロード" : "Downloads"}</span>
      </div>
      <div style={{ padding: tall ? "10px 0" : "8px 0", fontFamily: "Plex", fontSize: fs, color: C.ink }}>
        {[[file, "1 KB"], ...rows].map(([name, size], i) => (
          <div key={name} style={{ display: "flex", alignItems: "center", gap: 16, padding: tall ? "10px 22px" : "7px 18px",
            background: i === 0 && selOn ? C.cerulean : "transparent", color: i === 0 && selOn ? C.paper : C.ink,
            transform: i === 0 ? `translateX(${(1 - row) * -40}px)` : undefined, opacity: i === 0 ? row : 1 }}>
            <span style={{ width: fs * 0.9, height: fs * 1.1, border: `3px solid ${i === 0 && selOn ? C.paper : C.ink}`, flex: "none" }} />
            <span style={{ flex: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", fontWeight: i === 0 ? 700 : 400 }}>{name}</span>
            <span style={{ fontFamily: "Mark", fontSize: fs * 0.7 }}>{size}</span>
          </div>
        ))}
      </div>
    </div>
  );
};

/** 静止画を拍で切り替えて見せる（曲名リストの組み方など、録画より作った絵のほうが伝わるもの）。
    public/stills/<名前>.png（横は -pc）。切り替えごとに少し弾ませ、添え書きを枠の下に出す */
const Stills: React.FC<{ L: Layout; shot: Shot }> = ({ L, shot }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const names = shot.stills ?? [];
  const at = (shot.stillBeats ?? names.map((_, i) => i)).map((b) => beatFrame(shot.beat + b) - beatFrame(shot.beat));
  let idx = 0;
  for (let i = 0; i < at.length; i++) if (frame >= at[i]) idx = i;
  const s = spring({ frame: frame - at[idx], fps, config: { damping: 12, stiffness: 240 } });
  const tall = L.kind === "tall";
  const label = shot.labels?.[idx];
  if (shot.scrap) {
    // 決まった乱数（毎回同じ絵になるように）。角度 ±14°、位置は枠の中で ±22%・±26%
    const rnd = (i: number, k: number) => { const x = Math.sin((i + 1) * 12.9898 + k * 78.233) * 43758.5453; return x - Math.floor(x); };
    return (
      <div style={{ position: "absolute", inset: 0, background: C.paper, backgroundImage: `radial-gradient(${C.ink}18 1.2px, transparent 1.3px)`, backgroundSize: "14px 14px", overflow: "hidden" }}>
        {names.slice(0, idx + 1).map((n, i) => {
          // **場面の終わりまでに落ち着かせる**（v11、利用者の指摘）。最後の 1 枚は次の場面まで 4 コマほどしか無く、
          // 跳ねている途中で切り替わっていた。残りのコマが少ないカードは、その長さに縮めて着地させる（出る拍は変えない）
          const left = beatFrame(shot.beat + shot.len) - beatFrame(shot.beat) - at[i] - 1;
          const natural = measureSpring({ fps, config: { damping: 11, stiffness: 320 } });
          const k = spring({ frame: frame - at[i], fps, config: { damping: 11, stiffness: 320 }, ...(left < natural ? { durationInFrames: Math.max(1, left) } : {}) });
          // 枠は無し。画面全体（字幕の帯の下から下端まで）に散らばらせる（v7、利用者の指定）
          // 升目 4×4 に決まった順（真ん中と端が交互）で 1 枚ずつ置き、その中で揺らす（v9、利用者の指定: 終盤が真ん中に寄っていた）
          // 最後の 1 枚は左下（升目 12）に置く（v10、利用者の指定）
          const SLOTS = [0, 15, 5, 10, 3, 11, 6, 9, 1, 14, 7, 8, 2, 13, 4, 12];
          const slot = SLOTS[i % 16], gx = (slot % 4) / 3 - 0.5, gy = Math.floor(slot / 4) / 3 - 0.5;
          const rot = (rnd(i, 1) - 0.5) * 30;
          const dx = gx * (tall ? 80 : 150) + (rnd(i, 2) - 0.5) * (tall ? 18 : 30);
          const dy = gy * (tall ? 170 : 100) + (rnd(i, 3) - 0.5) * (tall ? 20 : 16) + (tall ? 10 : 6);
          return (
            <div key={n} style={{ position: "absolute", left: "50%", top: "50%", width: tall ? "62%" : "34%", transform: `translate(-50%, -50%) translate(${dx}%, ${dy}%) rotate(${rot}deg) scale(${1.25 - k * 0.25})`, opacity: Math.min(1, k * 1.6) }}>
              <div style={{ background: "#fff", padding: tall ? 10 : 8, boxShadow: `6px 6px 0 ${C.ink}`, border: `3px solid ${C.ink}` }}>
                <Img src={staticFile(`stills/${n}${tall ? "" : "-pc"}.png`)} style={{ width: "100%", display: "block" }} />
              </div>
            </div>
          );
        })}
      </div>
    );
  }
  return (
    <>
      <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", background: C.paper, transform: `scale(${0.94 + s * 0.06})` }}>
        <Img src={staticFile(`stills/${names[idx]}${tall ? "" : "-pc"}.png`)} style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain" }} />
      </div>
      {label && (
        <div style={{ position: "absolute", left: 0, right: 0, bottom: tall ? 28 : 20, display: "flex", justifyContent: "center", pointerEvents: "none" }}>
          <div style={{ background: C.ink, color: C.paper, fontFamily: L.lang === "ja" ? "Plex" : "Dot", fontWeight: 700, fontSize: tall ? 40 : 34, padding: "8px 26px", transform: `translateY(${(1 - s) * 20}px)`, opacity: s }}>
            {L.lang === "ja" ? label.jp : label.en}
          </div>
        </div>
      )}
    </>
  );
};

// ---- できあがり（2 小節）。本編の録画で作った 1 枚をそのまま見せる（v4、エディタで 4 枚の切り替えをやめた） ----
const Showcase: React.FC<{ L: Layout }> = ({ L }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { pulse, beat } = useBeatPulse(0.7);
  const s = spring({ frame, fps, config: { damping: 13, stiffness: 90 } });
  const { durationInFrames } = useVideoConfig();
  const drift = interpolate(frame, [0, durationInFrames], [1.0, 1.05], { extrapolateRight: "clamp" });
  const color = STRIPE[Math.max(0, beat) % 6];
  const img = L.kind === "tall"
    ? { left: 90, top: 200, width: 900, height: 1600 }
    : { left: 222, top: 215, width: 1476, height: 830 };
  const hit = 1;
  const src = RECORDINGS[L.kind][L.lang].main.final;
  return (
    <AbsoluteFill style={{ background: color }}>
      <AbsoluteFill style={{ backgroundImage: `radial-gradient(${C.ink}22 1.2px, transparent 1.3px)`, backgroundSize: "14px 14px" }} />
      <div style={{ position: "absolute", ...img, border: `6px solid ${C.ink}`, boxShadow: `16px 16px 0 ${C.ink}`, overflow: "hidden", background: C.paper, display: "flex", alignItems: "center", justifyContent: "center", transform: `scale(${s * (drift + pulse * 0.01) * (0.97 + hit * 0.03)})`, transformOrigin: "50% 50%" }}>
        <Img src={staticFile(src)} style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain" }} />
      </div>
      {L.kind === "tall" ? (
        <>
          <div style={{ position: "absolute", left: 90, top: 96, background: C.ink, color: C.paper, fontFamily: L.lang === "ja" ? "Plex" : "Dot", fontWeight: 700, fontSize: L.lang === "ja" ? 56 : 44, padding: "8px 24px", transform: `translateY(${(1 - s) * -30}px)`, opacity: s }}>{L.lang === "ja" ? "できあがり" : "Done in a minute"}</div>
          {L.lang === "ja" && <div style={{ position: "absolute", right: 90, top: 110, fontFamily: "Dot", fontSize: 36, color: C.ink, opacity: s }}>Done in a minute</div>}
        </>
      ) : (
        <div style={{ position: "absolute", left: 222, right: 222, top: 40, height: 160, display: "flex", alignItems: "flex-end", gap: 40, transform: `translateY(${(1 - s) * -30}px)`, opacity: s }}>
          <div style={{ background: C.ink, color: C.paper, fontFamily: L.lang === "ja" ? "Plex" : "Dot", fontWeight: 700, fontSize: L.lang === "ja" ? 60 : 48, padding: "10px 30px" }}>{L.lang === "ja" ? "できあがり" : "Done in a minute"}</div>
          {L.lang === "ja" && <div style={{ fontFamily: "Dot", fontSize: 40, color: C.ink, paddingBottom: 12 }}>Done in a minute</div>}
        </div>
      )}
    </AbsoluteFill>
  );
};

// ---- エンドカード（あなたは何曲オススメを？ → URL → 無料、1 小節ずつ） ----
const EndCard: React.FC<{ L: Layout }> = ({ L }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { pulse } = useBeatPulse();
  const s = spring({ frame, fps, config: { damping: 12, stiffness: 120 } });
  const s2 = spring({ frame: frame - 10, fps, config: { damping: 12, stiffness: 120 } });
  const sUrl = spring({ frame: frame - (beatFrame(URL_BEAT) - beatFrame(END_BEAT)), fps, config: { damping: 12, stiffness: 140 } });
  const sFree = spring({ frame: frame - (beatFrame(FREE_BEAT) - beatFrame(END_BEAT)), fps, config: { damping: 12, stiffness: 140 } });
  const fade = interpolate(frame, [beatFrame(TAIL_BEAT) - beatFrame(END_BEAT) - 6, beatFrame(TAIL_BEAT) - beatFrame(END_BEAT)], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const tall = L.kind === "tall";
  return (
    <Paper>
      <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", opacity: fade }}>
        <div style={{ transform: `scale(${s * (1 + pulse * 0.03)})` }}><Wordmark size={L.mark} /></div>
        <div style={{ marginTop: 24 }}><Stripe h={18} lead width={tall ? 1000 : 1400} /></div>
        <div style={{ marginTop: tall ? 80 : 56, display: "flex", flexDirection: tall ? "column" : "row", gap: tall ? 12 : 40, alignItems: tall ? "center" : "baseline", opacity: s2, transform: `translateY(${(1 - s2) * 30}px)` }}>
          {L.lang === "ja" && <div style={{ fontFamily: "Plex", fontWeight: 700, fontSize: tall ? 54 : 56, color: C.ink }}>あなたは何曲オススメを？</div>}
          <div style={{ fontFamily: "Dot", fontSize: L.lang === "ja" ? (tall ? 38 : 40) : (tall ? 50 : 52), color: L.lang === "ja" ? C.muted : C.ink }}>What would you pick?</div>
        </div>
        <div style={{ marginTop: tall ? 90 : 60, background: C.ink, color: C.paper, fontFamily: "Mark", fontWeight: 700, fontSize: tall ? 44 : 48, padding: "18px 40px", letterSpacing: "0.04em", opacity: sUrl, transform: `scale(${0.8 + sUrl * 0.2})` }}>trackmento.com</div>
        <div style={{ marginTop: 28, fontFamily: "Dot", fontSize: 32, color: C.muted, opacity: sFree, transform: `translateY(${(1 - sFree) * 20}px)` }}>{L.lang === "ja" ? "無料・登録なし / Free, no sign-up" : "Free, no sign-up"}</div>
      </AbsoluteFill>
    </Paper>
  );
};

// ---- つかみ（2 小節。作った画）: 同じ 9 本の動画を、正方形のマス（左右が切れる）4 拍 → 横長 16:9 のマス（全部見える）4 拍 ----
// 画は promo/make_stills.py --hook が本編の並びから作る（public/stills/hook-square.png・hook-wide.png。サーバー描画）
/** つかみの 2 枚の縦横比（make_stills.py --hook の出力。正方形のマス 3×3 と 16:9 のマス 3×3、余白込み） */
const HOOK_AR = { square: 1, wide: 1600 / 967 };
const Hook: React.FC<{ L: Layout }> = ({ L }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const switchAt = beatFrame(HOOK_BEAT + BAR) - beatFrame(HOOK_BEAT);
  const after = frame >= switchAt;
  const s = spring({ frame: frame - (after ? switchAt : 0), fps, config: { damping: 13, stiffness: 200 } });
  const tall = L.kind === "tall", ja = L.lang === "ja";
  const box = tall ? { left: 60, top: 380, width: 960, height: 1400 } : { left: 260, top: 200, width: 1400, height: 840 };
  return (
    <Paper>
      <div style={{ position: "absolute", left: 0, right: 0, top: 0 }}><Stripe h={14} /></div>
      <Caption L={L} jp={"動画のサムネを、\n切らずに並べる"} en={"Video thumbnails,\nuncropped"} />
      {/* **画像の大きさは枠いっぱいに計算して決める**（max-width 任せだと小さく縮んでいた。2026-09-21 の確認で後半の 16:9 が枠の半分ほどだった） */}
      {(() => {
        const ar = after ? HOOK_AR.wide : HOOK_AR.square, H = box.height - (tall ? 60 : 50);
        const w = Math.min(box.width, H * ar), h = w / ar;
        // **画面の中央に置く**（2026-09-22、利用者の指摘。上に寄せていて、縦では下半分が空いていた）。
        // 縦は画面の真ん中、横は字幕の帯の下から下端までの真ん中。札は画像の右上のすぐ上
        const cy = tall ? L.H / 2 : (box.top + L.H) / 2;
        const top = Math.max(box.top + (tall ? 50 : 40), cy - h / 2), left = box.left + (box.width - w) / 2;
        return (
          <>
            <div style={{ position: "absolute", left, top, width: w, height: h,
              transform: `scale(${0.92 + s * 0.08})`, opacity: Math.min(1, 0.4 + s), border: `6px solid ${C.ink}`, boxShadow: `14px 14px 0 ${C.ink}`, boxSizing: "content-box", overflow: "hidden" }}>
              <Img src={staticFile(`stills/${after ? "hook-wide" : "hook-square"}.png`)} style={{ width: "100%", height: "100%", display: "block" }} />
            </div>
            {/* 札: 前半は「正方形」（左右が切れる）、後半は「横長 16:9」 */}
            <div style={{ position: "absolute", left, width: w + 12, top: top - (tall ? 64 : 54), display: "flex", justifyContent: "flex-end" }}>
              <div style={{ background: after ? C.vermilion : C.muted, color: C.paper, fontFamily: ja ? "Plex" : "Dot", fontWeight: 700,
                fontSize: tall ? 42 : 38, padding: "8px 24px", border: `4px solid ${C.ink}`, transform: `translateY(${(1 - s) * 20}px) scale(${0.85 + s * 0.15})`, opacity: s }}>
                {after ? (ja ? "横長 16:9 のマス" : "16:9 cells") : (ja ? "正方形のマス（左右が切れる）" : "Square cells (sides cut)")}
              </div>
            </div>
          </>
        );
      })()}
    </Paper>
  );
};

/** 3 つの特徴の背景のドット（2026-09-22、利用者の指定）。色は**3 行の四角に使っていない 3 色**（STRIPE の 1・3・5 番目）。
    ドット（四角）は市松に 2 組へ分け、1 拍ごとに片方が大きく・もう片方が小さくなって入れ替わる */
const PointsDots: React.FC<{ L: Layout }> = ({ L }) => {
  const frame = useCurrentFrame();
  const tall = L.kind === "tall";
  const beatLen = beatFrame(POINTS_BEAT + 1) - beatFrame(POINTS_BEAT);
  const b = frame / beatLen, k = b - Math.floor(b);
  const e = k < 0.5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2;   // 1 拍の中でなめらかに
  const grow = Math.floor(b) % 2 === 0 ? e : 1 - e;            // 組 A の大きさ（0〜1）。組 B は逆
  const COLORS = [STRIPE[1], STRIPE[3], STRIPE[5]];
  const gap = tall ? 150 : 160, r0 = tall ? 7 : 7, r1 = tall ? 22 : 22;
  const cols = Math.ceil(L.W / gap) + 1, rows = Math.ceil(L.H / gap) + 1;
  const dots: React.ReactNode[] = [];
  // **文字の塊のまわりは空ける**（ドットが英語の行に重なって読みづらかった）。縦は真ん中の帯、横は真ん中の四角
  const clear = tall ? { x0: -1, x1: L.W + 1, y0: 600, y1: 1330 } : { x0: 320, x1: 1600, y0: 220, y1: 890 };
  for (let y = 0; y < rows; y++) for (let x = 0; x < cols; x++) {
    const px = gap / 2 + x * gap, py = gap / 2 + y * gap;
    if (px > clear.x0 && px < clear.x1 && py > clear.y0 && py < clear.y1) continue;
    const a = (x + y) % 2 === 0, g = a ? grow : 1 - grow;
    const r = r0 + (r1 - r0) * g;   // **四角**（2026-09-22、利用者の指定。ロゴの下線の四角と同じ形）。r は一辺の半分
    dots.push(<rect key={`${x}-${y}`} x={px - r} y={py - r} width={r * 2} height={r * 2} fill={COLORS[(x + y * 2) % 3]} />);
  }
  return <svg width={L.W} height={L.H} style={{ position: "absolute", inset: 0 }}>{dots}</svg>;
};

// ---- 3 つの特徴（3 小節。作った画）: 見出しのあと、1 小節に 1 行ずつ ----
const Points: React.FC<{ L: Layout }> = ({ L }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const tall = L.kind === "tall", ja = L.lang === "ja";
  const head = spring({ frame, fps, config: { damping: 13, stiffness: 160 } });
  return (
    <Paper>
      <PointsDots L={L} />
      <div style={{ position: "absolute", left: 0, right: 0, top: 0 }}><Stripe h={14} /></div>
      <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", flexDirection: "column", gap: tall ? 56 : 36 }}>
        <div style={{ fontFamily: "Mark", fontWeight: 700, fontSize: tall ? 84 : 96, color: C.ink, letterSpacing: "0.06em", opacity: head, transform: `translateY(${(1 - head) * -30}px)` }}>TRACKMENTO</div>
        <div style={{ display: "flex", flexDirection: "column", gap: tall ? 30 : 22, alignItems: "stretch", minWidth: tall ? 820 : 980 }}>
          {POINTS.map((p, i) => {
            const at = beatFrame(POINTS_BEAT + BAR * i) - beatFrame(POINTS_BEAT);
            const k = spring({ frame: frame - at, fps, config: { damping: 12, stiffness: 200 } });
            return (
              <div key={p.jp} style={{ display: "flex", alignItems: "center", gap: 24, opacity: k, transform: `translateX(${(1 - k) * -60}px)` }}>
                <div style={{ width: tall ? 54 : 58, height: tall ? 54 : 58, flex: "none", background: STRIPE[(i * 2) % 6], border: `4px solid ${C.ink}`, fontFamily: "Silk", fontWeight: 700, fontSize: tall ? 30 : 32, display: "flex", alignItems: "center", justifyContent: "center", color: C.ink }}>{i + 1}</div>
                <div style={{ background: C.ink, color: C.paper, fontFamily: ja ? "Plex" : "Dot", fontWeight: 700, fontSize: tall ? 60 : 62, padding: tall ? "10px 28px" : "10px 32px", flex: 1 }}>{ja ? p.jp : p.en}</div>
              </div>
            );
          })}
        </div>
        {ja && <div style={{ fontFamily: "Dot", fontSize: tall ? 34 : 36, color: C.muted, opacity: head }}>{POINTS.map((p) => p.en).join(" / ")}</div>}
      </AbsoluteFill>
    </Paper>
  );
};

// ---- 本体 ----
export const Promo: React.FC<{ layout: LayoutKind; lang?: Lang }> = ({ layout, lang = "ja" }) => {
  const L: Layout = { ...LAYOUTS[layout], lang };
  // 2026-09-21: 録画のショットはエンドカードの前まで続く（できあがりの後にも録画がある）。作った画はその上に重ねる
  const walkFrom = SHOTS[0].beat;
  const afterShowcase = SHOTS.find((s) => s.beat >= SHOWCASE_BEAT)?.beat ?? END_BEAT;
  return (
    <AbsoluteFill style={{ background: C.paper }}>
      {/* 音源そのものが大きく、そのまま入れると割れる（とくに頭）。全体を下げてから、
          エンドカードの頭でフェードアウトする */}
      <Audio src={staticFile("sherbet.mp3")} volume={(f) => 0.55 * interpolate(f, [beatFrame(FADE_FROM), beatFrame(LAST_BEAT)], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })} />
      <Sequence from={0} durationInFrames={beatFrame(INTRO_END)} name="Intro"><Paper><Intro L={L} /></Paper></Sequence>
      <Sequence from={beatFrame(HOOK_BEAT)} durationInFrames={beatFrame(POINTS_BEAT) - beatFrame(HOOK_BEAT)} name="Hook"><Hook L={L} /></Sequence>
      <Sequence from={beatFrame(POINTS_BEAT)} durationInFrames={beatFrame(walkFrom) - beatFrame(POINTS_BEAT)} name="Points"><Points L={L} /></Sequence>

      <Sequence from={beatFrame(walkFrom)} durationInFrames={beatFrame(END_BEAT) - beatFrame(walkFrom)} name="Walkthrough">
        <Paper>
          <div style={{ position: "absolute", left: 0, right: 0, top: 0 }}><Stripe h={14} /></div>
          {SHOTS.map((s, i) => shotSeq(L, s, Math.min(SHOTS[i + 1]?.beat ?? END_BEAT, s.beat + s.len), walkFrom))}
        </Paper>
      </Sequence>

      <Sequence from={beatFrame(SHOWCASE_BEAT)} durationInFrames={beatFrame(afterShowcase) - beatFrame(SHOWCASE_BEAT)} name="Showcase"><Showcase L={L} /></Sequence>
      <Sequence from={beatFrame(END_BEAT)} durationInFrames={beatFrame(TAIL_BEAT) - beatFrame(END_BEAT)} name="End"><EndCard L={L} /></Sequence>
      {/* エンドカードのあとに「困ったら使い方」（録画） */}
      <Sequence from={beatFrame(TAIL_BEAT)} name="Tail">
        <Paper>
          <div style={{ position: "absolute", left: 0, right: 0, top: 0 }}><Stripe h={14} /></div>
          {TAIL_SHOTS.map((s, i) => shotSeq(L, s, TAIL_SHOTS[i + 1]?.beat ?? LAST_BEAT, TAIL_BEAT))}
        </Paper>
      </Sequence>
    </AbsoluteFill>
  );
};

/** キメで寄り、最後のキメから横へ引き伸ばして白へ（2026-09-21、タイムラプスから共有の場面へ移した演出）。
    frame はショットの頭から。kime はショットの頭からの拍 */
function kimeFx(s: Shot, frame: number, fps: number, total: number) {
  let zoom = 1, stretch = 0, white = 0;
  if (!s.kime) return { zoom, stretch, white };
  const hits = s.kime.map((b) => beatFrame(s.beat + b) - beatFrame(s.beat));
  hits.forEach((at, i) => {
    const k = spring({ frame: frame - at, fps, config: { damping: 12, stiffness: 260 } });
    zoom += k * 0.09;
    // 最後のキメから場面の終わりまで、最初が速い曲線で横に 3 倍まで伸ばし続け、白も同じ曲線で被せる（v7・v8 の利用者の指定）
    if (i === hits.length - 1) {
      const k2 = interpolate(frame, [at, total], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) });
      stretch = k2 * 2; white = k2;
    }
  });
  return { zoom, stretch, white };
}
const KimeWrap: React.FC<{ s: Shot; children?: React.ReactNode; phase: "stretch" | "white" }> = ({ s, children, phase }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const { zoom, stretch, white } = kimeFx(s, frame, fps, durationInFrames);
  if (phase === "white") return <AbsoluteFill style={{ background: "#ffffff", opacity: white, pointerEvents: "none" }} />;
  return <AbsoluteFill style={{ transform: `scaleX(${1 + stretch}) scale(${zoom})`, transformOrigin: "50% 50%" }}>{children}</AbsoluteFill>;
};

/** 横のショットのカメラの点。ショットの頭より前の最後の操作 ＋ ショットのあいだの操作 */
function shotCam(L: Layout, s: Shot, next: number): CamKey[] {
  const sess = s.rec ?? "main", r = rate(L.kind, L.lang, sess) * (s.speed ?? 1);
  const from = evTime(L.kind, L.lang, sess, s.ev) + s.off * rate(L.kind, L.lang, sess);
  const to = from + (beatTime(next) - beatTime(s.beat)) * r;
  const all = evRects(L.kind, L.lang, sess);
  const before = all.filter((e) => e.t <= from).slice(-1), inside = all.filter((e) => e.t > from && e.t <= to + CAM_LEAD);
  return [...before, ...inside].map((e) => camKey(e.t, e.rect));
}

/** 録画（または静止画）のショット 1 つ。base = 親の Sequence の頭の拍 */
function shotSeq(L: Layout, s: Shot, next: number, base: number) {
  return (
              <Sequence key={s.beat} from={beatFrame(s.beat) - beatFrame(base)} durationInFrames={beatFrame(next) - beatFrame(s.beat)} name={s.jp || "countdown"}>
                {s.scrap && <Stills L={L} shot={s} />}
                {s.scrap && <div style={{ position: "absolute", inset: 0, zIndex: 2 }}><Caption L={L} jp={s.jp} en={s.en} /></div>}
                {/* キメで寄るショットは録画が字幕の上に被るので、字幕を前に出す（2026-09-21） */}
                {!s.scrap && <div style={{ position: "absolute", inset: 0, zIndex: s.kime ? 2 : undefined, pointerEvents: "none" }}><Caption L={L} jp={s.jp} en={s.en} still={s.capStill} delay={s.fx === "flashIn" ? beatFrame(s.beat + 1) - beatFrame(s.beat) : 0}>{s.sites && <SiteBadges L={L} startBeat={s.beat} />}</Caption></div>}
                {!s.scrap && (() => {
                  const phone = (
                    <Phone L={L} fx={s.fx}>
                      {s.stills ? (
                        <Stills L={L} shot={s} />
                      ) : (
                        <Clip kind={L.kind} lang={L.lang} session={s.rec ?? "main"} from={evTime(L.kind, L.lang, s.rec ?? "main", s.ev) + s.off * rate(L.kind, L.lang, s.rec ?? "main")} speed={s.speed} zoom={L.kind === "wide" ? s.zoomPc : s.zoom} still={s.still}
                          cam={L.kind === "wide" && !s.hlEv ? shotCam(L, s, next) : undefined} />
                      )}
                      {L.kind === "tall" && s.hl && <Highlight L={L} hl={s.hl} />}
                      {/* 赤枠は録画の印の位置（markRect）から。縦・横とも。ズームしているショットには付けない（位置がずれる） */}
                      {s.hlEv && <Highlight L={L} hl={evRect(L.kind, L.lang, s.rec ?? "main", s.hlEv)} />}
                    </Phone>
                  );
                  return s.kime ? <><KimeWrap s={s} phase="stretch">{phone}</KimeWrap><div style={{ position: "absolute", inset: 0, zIndex: 3 }}><KimeWrap s={s} phase="white" /></div></> : phone;
                })()}
                {s.fx === "flashIn" && <FlashIn />}
                {s.explorer && (() => {
                  // 録画の中で保存した時刻 → このショットの何コマ目か（Clip の再生速度で割る）
                  const sess = s.rec ?? "main", r = rate(L.kind, L.lang, sess) * (s.speed ?? 1);
                  const from = evTime(L.kind, L.lang, sess, s.ev) + s.off * rate(L.kind, L.lang, sess);
                  const ex = s.explorer!, rel = (b: number) => beatFrame(s.beat + b) - beatFrame(s.beat);
                  // 拍が決めてあればそれに乗せる（キメのレーン）。無ければ録画で保存した時刻
                  const at = ex.beats ? rel(ex.beats[0]) : Math.round(((evTime(L.kind, L.lang, sess, ex.ev) - from) / r) * FPS);
                  const ev = RECORDINGS[L.kind][L.lang][sess].events.find((e) => e.name === ex.ev) as { file?: string } | undefined;
                  return <Sequence from={at} layout="none"><SavedWindow L={L} file={ex.file ?? ev?.file ?? "trackmento-palette.json"}
                    rowAt={ex.beats ? rel(ex.beats[1]) - at : undefined} blinkAt={ex.beats ? rel(ex.beats[2]) - at : undefined}
                    hideAt={ex.hide !== undefined ? rel(ex.hide) - at : undefined} /></Sequence>;
                })()}
              </Sequence>
  );
}
