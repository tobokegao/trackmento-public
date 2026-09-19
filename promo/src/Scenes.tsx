// TRACKMENTO 紹介動画。9:16（tall）と 16:9（wide）を同じ部品・同じ拍割りで描く。拍割りは timeline.ts
import React from "react";
import {
  AbsoluteFill, Audio, Freeze, Img, OffthreadVideo, Sequence, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig, Easing,
} from "remotion";
import { loadFont } from "@remotion/fonts";
import {
  FPS, BAR, beatTime, beatFrame, sec, evTime, rate, RECORDINGS, SHOTS, TIMELAPSE_KIME, SITES, SITES_EN, BANDWIDTH_ROWS, Shot, Kind, Lang,
  INTRO_END, TIMELAPSE_BEAT, SHOWCASE_BEAT, NEWURL_BEAT, BANDWIDTH_BEAT, FASTER_BEAT, FASTER_ROWS, TAIL_BEAT, TAIL_SHOTS, END_BEAT, URL_BEAT, FREE_BEAT, LAST_BEAT, FADE_FROM, timelapseTimes, TIMELAPSE_STEPS,
} from "./timeline";

// ---- フォント（アプリと同じ OFL 同梱フォント） ----
loadFont({ family: "Plex", url: staticFile("fonts/IBMPlexSansJP-Bold.ttf"), weight: "700" });
loadFont({ family: "Plex", url: staticFile("fonts/IBMPlexSansJP-Regular.ttf"), weight: "400" });
loadFont({ family: "Silk", url: staticFile("fonts/Silkscreen-Bold.ttf"), weight: "700" });
loadFont({ family: "Mark", url: staticFile("fonts/TrackmentoMark-Bold.ttf"), weight: "700" });   // ロゴ専用（M だけ描き替えた Silkscreen。scripts/build_logo_font.py）
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
const Caption: React.FC<{ L: Layout; jp: string; en: string; children?: React.ReactNode; delay?: number }> = ({ L, jp, en, children, delay = 0 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame: frame - delay, fps, config: { damping: 12, stiffness: 170 } });
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

/** ⑤ 見た目の見くらべ。前半 2 拍が v1 の画、後半が今の録画（スクロールバーはこちらで動く） */
const BeforeAfter: React.FC<{ L: Layout; file: string; zoom?: Shot["zoom"]; children: React.ReactNode }> = ({ L, file, zoom, children }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const switchAt = beatFrame(BAR) - beatFrame(0);   // 1 小節で切り替える（BEFORE 4 拍 / NOW 4 拍）
  const before = frame < switchAt;
  const s = spring({ frame: frame - (before ? 0 : switchAt), fps, config: { damping: 13, stiffness: 220 } });
  const tall = L.kind === "tall";
  return (
    <>
      {before
        ? <div style={{ width: "100%", height: "100%", transform: `scale(${zoom ? zoom.s : 1.03})`, transformOrigin: zoom ? `${zoom.x * 100}% ${zoom.y * 100}%` : "50% 50%" }}>
            <Img src={staticFile(`${file}${tall ? "" : "-pc"}.png`)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
          </div>
        : children}

    </>
  );
};

/** ⑤ の見くらべで出す BEFORE / NOW の札。Phone は overflow: hidden なので枠の外に別に置く */
const AbBadge: React.FC<{ L: Layout }> = ({ L }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const switchAt = beatFrame(BAR) - beatFrame(0);
  const before = frame < switchAt;
  const s = spring({ frame: frame - (before ? 0 : switchAt), fps, config: { damping: 13, stiffness: 220 } });
  const tall = L.kind === "tall";
  return (
    // 字幕（日本語＋英語の 2 段）より下、録画の枠のすぐ上に置く。
    // 字幕の裏に回しつつ、文字どうしが重ならない高さ
    <div style={{ position: "absolute", left: L.phone.x, width: L.phone.w, top: L.phone.y - (tall ? 96 : 74),
      display: "flex", justifyContent: "flex-end", pointerEvents: "none" }}>
      <div style={{ background: before ? C.muted : C.vermilion, color: C.paper, fontFamily: "Silk", fontWeight: 700,
        fontSize: tall ? 46 : 40, padding: "8px 26px", border: `4px solid ${C.ink}`,
        transform: `translateY(${(1 - s) * 20}px) scale(${0.85 + s * 0.15})`, opacity: s }}>
        {before ? "BEFORE" : "AFTER"}
      </div>
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

const Clip: React.FC<{ kind: Kind; lang: Lang; session: "main" | "feat"; from: number; speed?: number; zoom?: Shot["zoom"]; still?: boolean }> = ({ kind, lang, session, from, speed = 1, zoom, still }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const z = zoom ? interpolate(frame, [0, fps * 0.5], [1.03, zoom.s], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) }) : 1.03;
  const origin = zoom ? `${zoom.x * 100}% ${zoom.y * 100}%` : "50% 50%";
  const video = <OffthreadVideo src={staticFile(RECORDINGS[kind][lang][session].src)} startFrom={sec(from)} playbackRate={rate(kind, lang, session) * speed} muted style={{ width: "100%", height: "100%", objectFit: "cover" }} />;
  return (
    <div style={{ width: "100%", height: "100%", transform: `scale(${z})`, transformOrigin: origin }}>
      {still ? <Freeze frame={0}>{video}</Freeze> : video}
    </div>
  );
};

/** ファイルが保存された窓。frame 0 = 保存した瞬間。名前は録画の events.json（pal:saved の file）から */
const SavedWindow: React.FC<{ L: Layout; file: string }> = ({ L, file }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  if (frame < 0) return null;
  const s = spring({ frame, fps, config: { damping: 13, stiffness: 200 } });
  const row = spring({ frame: frame - 8, fps, config: { damping: 14, stiffness: 220 } });
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
            background: i === 0 ? C.cerulean : "transparent", color: i === 0 ? C.paper : C.ink,
            transform: i === 0 ? `translateX(${(1 - row) * -40}px)` : undefined, opacity: i === 0 ? row : 1 }}>
            <span style={{ width: fs * 0.9, height: fs * 1.1, border: `3px solid ${i === 0 ? C.paper : C.ink}`, flex: "none" }} />
            <span style={{ flex: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", fontWeight: i === 0 ? 700 : 400 }}>{name}</span>
            <span style={{ fontFamily: "Silk", fontSize: fs * 0.7 }}>{size}</span>
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
          const k = spring({ frame: frame - at[i], fps, config: { damping: 11, stiffness: 320 } });
          const rot = (rnd(i, 1) - 0.5) * 28, dx = (rnd(i, 2) - 0.5) * 44, dy = (rnd(i, 3) - 0.5) * 52;
          return (
            <div key={n} style={{ position: "absolute", left: "50%", top: "50%", width: "74%", transform: `translate(-50%, -50%) translate(${dx}%, ${dy}%) rotate(${rot}deg) scale(${1.25 - k * 0.25})`, opacity: Math.min(1, k * 1.6) }}>
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

// ---- タイムラプス（1 小節に 16 コマ） ----
const Timelapse: React.FC<{ L: Layout }> = ({ L }) => {
  const times = timelapseTimes(L.kind, L.lang);
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const total = beatFrame(SHOWCASE_BEAT) - beatFrame(TIMELAPSE_BEAT);   // できあがりまで（2 小節）
  const per = total / TIMELAPSE_STEPS;
  // キメ（エディタの「キメ」のレーン）ごとに一段ずつ寄る。最後の 1 つは**枠ごと**横に 2 倍まで引き伸ばす（v5、利用者の指定。v4 は横へ振っていた）
  const hits = TIMELAPSE_KIME.map((b) => beatFrame(TIMELAPSE_BEAT + b) - beatFrame(TIMELAPSE_BEAT));
  let zoom = 1, stretch = 0;
  hits.forEach((at, i) => {
    const k = spring({ frame: frame - at, fps, config: { damping: 12, stiffness: 260 } });
    zoom += k * 0.09;
    if (i === hits.length - 1) stretch += k * 1.0;
  });
  return (
    <>
      <Caption L={L} jp="画像完成まで" en="Start to finish" />
      <AbsoluteFill style={{ transform: `scaleX(${1 + stretch})`, transformOrigin: "50% 50%" }}>
      <Phone L={L}>
        <div style={{ width: "100%", height: "100%", transform: `scale(${zoom})`, transformOrigin: "50% 45%" }}>
        {times.map((t, i) => (
          <Sequence key={i} from={Math.round(i * per)} durationInFrames={Math.ceil(per) + 1} layout="none">
            <OffthreadVideo src={staticFile(RECORDINGS[L.kind][L.lang].main.src)} startFrom={sec(t)} playbackRate={rate(L.kind, L.lang, "main")} muted style={{ width: "100%", height: "100%", objectFit: "cover", transform: "scale(1.03)" }} />
          </Sequence>
        ))}
        </div>
      </Phone>
      </AbsoluteFill>
    </>
  );
};

// ---- できあがり（2 小節）。本編の録画で作った 1 枚をそのまま見せる（v4、エディタで 4 枚の切り替えをやめた） ----
const Showcase: React.FC<{ L: Layout }> = ({ L }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { pulse, beat } = useBeatPulse(0.7);
  const s = spring({ frame, fps, config: { damping: 13, stiffness: 90 } });
  const drift = interpolate(frame, [0, beatFrame(END_BEAT) - beatFrame(SHOWCASE_BEAT)], [1.0, 1.05]);
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
        <div style={{ marginTop: tall ? 90 : 60, background: C.ink, color: C.paper, fontFamily: "Silk", fontWeight: 700, fontSize: tall ? 44 : 48, padding: "18px 40px", letterSpacing: "0.04em", opacity: sUrl, transform: `scale(${0.8 + sUrl * 0.2})` }}>trackmento.com</div>
        <div style={{ marginTop: 28, fontFamily: "Dot", fontSize: 32, color: C.muted, opacity: sFree, transform: `translateY(${(1 - sFree) * 20}px)` }}>{L.lang === "ja" ? "無料・登録なし / Free, no sign-up" : "Free, no sign-up"}</div>
      </AbsoluteFill>
    </Paper>
  );
};

// ---- 新しい URL（2 小節。録画ではなく作った画。Playwright の録画にはアドレス欄が映らないため） ----
// 1 小節目: 古い URL が出て 2 拍目で取り消し線、3 拍目から矢印と新しい URL
// 2 小節目: 「並びもそのまま引っ越し」を 8 分音符で点滅させる
const NewUrl: React.FC<{ L: Layout }> = ({ L }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const beatLen = beatFrame(1) - beatFrame(0);
  const tall = L.kind === "tall";
  const ja = L.lang === "ja";
  const sOld = spring({ frame, fps, config: { damping: 13, stiffness: 160 } });
  const strike = interpolate(frame, [beatLen, beatLen * 1.5], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) });
  const sNew = spring({ frame: frame - beatLen * 2, fps, config: { damping: 11, stiffness: 150 } });
  const eighth = beatLen / 2;
  const blinkFrom = beatLen * 4 + eighth;
  const blinkOn = frame >= blinkFrom && Math.floor((frame - blinkFrom) / eighth) % 2 === 0;
  const urlBox = (dark: boolean): React.CSSProperties => ({
    fontFamily: "Silk", fontWeight: 700, fontSize: tall ? 50 : 60, letterSpacing: "0.04em", padding: "14px 34px",
    background: dark ? C.ink : "transparent", color: dark ? C.paper : C.muted, border: `4px solid ${dark ? C.ink : C.muted}`, whiteSpace: "nowrap",
  });
  return (
    <Paper>
      <div style={{ position: "absolute", left: 0, right: 0, top: 0 }}><Stripe h={14} /></div>
      <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", flexDirection: "column", gap: tall ? 44 : 30 }}>
        <div style={{ background: C.ink, color: C.paper, fontFamily: ja ? "Plex" : "Dot", fontWeight: 700, fontSize: tall ? 58 : 60, padding: "12px 30px", opacity: sOld, transform: `translateY(${(1 - sOld) * -30}px)` }}>
          {ja ? "新しい URL になりました" : "We have a new address"}
        </div>
        <div style={{ position: "relative", opacity: sOld }}>
          <div style={urlBox(false)}>trackmento.onrender.com</div>
          <div style={{ position: "absolute", left: 20, right: 20, top: "50%", height: 6, marginTop: -3, background: C.vermilion, transformOrigin: "0 50%", transform: `scaleX(${strike})` }} />
        </div>
        <div style={{ fontFamily: "Silk", fontWeight: 700, fontSize: tall ? 70 : 64, color: C.ink, opacity: sNew, transform: `translateY(${(1 - sNew) * -20}px)` }}>↓</div>
        <div style={{ ...urlBox(true), fontSize: tall ? 64 : 76, boxShadow: `10px 10px 0 ${C.mustard}`, opacity: sNew, transform: `scale(${0.8 + sNew * 0.2})` }}>trackmento.com</div>
        <div style={{ marginTop: tall ? 20 : 8, fontFamily: ja ? "Plex" : "Dot", fontWeight: 700, fontSize: tall ? 40 : 40, color: C.ink, opacity: blinkOn ? 1 : 0 }}>
          {ja ? "前の URL から開いても、並びごと引っ越し" : "Old links still work — your grids move with you"}
        </div>
      </AbsoluteFill>
    </Paper>
  );
};

// ---- ⑥「動作が軽くなりました」（2 小節。録画ではなく数字を出す） ----
// 1 小節目: 画面いっぱいの見出しを 2 拍で中央まで縮め、残り 2 拍で見出しが上がりつつ 4 行が出る
// 2 小節目: 「画質はそのまま」を 8 分音符で点滅させ続ける
type NumRow = { jp: string; en: string; from: string; to: string };
const Bandwidth: React.FC<{ L: Layout; title?: [string, string]; rows?: NumRow[]; blink?: [string, string] }> = ({ L, title = ["さらに軽くなりました", "Even lighter now"], rows = BANDWIDTH_ROWS, blink = ["画質はそのまま", "Same image quality"] }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const beatLen = beatFrame(1) - beatFrame(0);
  const tall = L.kind === "tall";
  const ja = L.lang === "ja";

  const shrink = interpolate(frame, [0, Math.round(beatLen * 1.1)], [3, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.exp) });
  const rise = spring({ frame: frame - beatLen * 2, fps, config: { damping: 14, stiffness: 110 } });
  const eighth = beatLen / 2;
  const blinkFrom = beatLen * 4 + eighth;                          // 2 小節目の裏拍から
  const blinkOn = frame >= blinkFrom && Math.floor((frame - blinkFrom) / eighth) % 2 === 0;

  return (
    <Paper>
      <div style={{ position: "absolute", left: 0, right: 0, top: 0 }}><Stripe h={14} /></div>
      <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", padding: tall ? "0 60px" : "0 200px" }}>
        <div style={{ background: C.ink, color: C.paper, fontFamily: ja ? "Plex" : "Dot", fontWeight: 700,
          fontSize: tall ? 58 : 60, padding: "12px 30px", whiteSpace: "nowrap",
          transform: `translateY(${-rise * (tall ? 300 : 190)}px) scale(${shrink})` }}>
          {ja ? title[0] : title[1]}
        </div>
        <div style={{ position: "absolute", left: tall ? 60 : 200, right: tall ? 60 : 200, top: "46%",
          display: "flex", flexDirection: "column", gap: tall ? 18 : 14, opacity: rise }}>
          {rows.map((r, i) => {
            const k = spring({ frame: frame - beatLen * 2 - Math.round(eighth * i), fps, config: { damping: 12, stiffness: 220 } });
            return (
              <div key={r.jp} style={{ display: "flex", alignItems: "baseline", gap: tall ? 16 : 24, transform: `translateX(${(1 - k) * -30}px)`, opacity: k }}>
                <div style={{ fontFamily: ja ? "Plex" : "Dot", fontWeight: 700, fontSize: tall ? 34 : 36, color: C.ink, flex: 1 }}>{ja ? r.jp : r.en}</div>
                <div style={{ fontFamily: "Silk", fontWeight: 700, fontSize: tall ? 30 : 32, color: C.muted, textDecoration: "line-through" }}>{r.from}</div>
                <div style={{ fontFamily: ja ? "Plex" : "Silk", fontWeight: 700, fontSize: tall ? 32 : 34, color: C.paper, background: STRIPE[i % 6], padding: "2px 12px", border: `3px solid ${C.ink}` }}>{r.to}</div>
              </div>
            );
          })}
        </div>
        <div style={{ position: "absolute", left: 0, right: 0, bottom: tall ? 150 : 90, textAlign: "center",
          fontFamily: ja ? "Plex" : "Dot", fontWeight: 700, fontSize: 40, color: C.ink,
          opacity: blinkOn ? 1 : 0 }}>
          {ja ? blink[0] : blink[1]}
        </div>
      </AbsoluteFill>
    </Paper>
  );
};


// ---- 本体 ----
export const Promo: React.FC<{ layout: LayoutKind; lang?: Lang }> = ({ layout, lang = "ja" }) => {
  const L: Layout = { ...LAYOUTS[layout], lang };
  const flowEnd = beatFrame(TIMELAPSE_BEAT);
  return (
    <AbsoluteFill style={{ background: C.paper }}>
      {/* 音源そのものが大きく、そのまま入れると割れる（とくに頭）。全体を下げてから、
          エンドカードの頭でフェードアウトする */}
      <Audio src={staticFile("sherbet.mp3")} volume={(f) => 0.55 * interpolate(f, [beatFrame(FADE_FROM), beatFrame(LAST_BEAT)], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })} />
      <Sequence from={0} durationInFrames={beatFrame(INTRO_END)} name="Intro"><Paper><Intro L={L} /></Paper></Sequence>

      <Sequence from={beatFrame(INTRO_END)} durationInFrames={flowEnd - beatFrame(INTRO_END)} name="Walkthrough">
        <Paper>
          <div style={{ position: "absolute", left: 0, right: 0, top: 0 }}><Stripe h={14} /></div>
          {SHOTS.map((s, i) => shotSeq(L, s, SHOTS[i + 1]?.beat ?? TIMELAPSE_BEAT, INTRO_END))}
        </Paper>
      </Sequence>

      <Sequence from={beatFrame(NEWURL_BEAT)} durationInFrames={beatFrame(NEWURL_BEAT + BAR * 2) - beatFrame(NEWURL_BEAT)} name="NewUrl"><NewUrl L={L} /></Sequence>
      <Sequence from={beatFrame(BANDWIDTH_BEAT)} durationInFrames={beatFrame(BANDWIDTH_BEAT + BAR * 2) - beatFrame(BANDWIDTH_BEAT)} name="Bandwidth"><Bandwidth L={L} /></Sequence>
      <Sequence from={beatFrame(FASTER_BEAT)} durationInFrames={beatFrame(FASTER_BEAT + BAR * 2) - beatFrame(FASTER_BEAT)} name="Faster">
        <Bandwidth L={L} title={["共有がさらに速く", "Sharing is faster"]} rows={FASTER_ROWS} blink={["X での見た目はほぼそのまま", "Looks the same on X"]} />
      </Sequence>

      <Sequence from={beatFrame(TIMELAPSE_BEAT)} durationInFrames={beatFrame(SHOWCASE_BEAT) - beatFrame(TIMELAPSE_BEAT)} name="Timelapse">
        <Paper><div style={{ position: "absolute", left: 0, right: 0, top: 0 }}><Stripe h={14} /></div><Timelapse L={L} /></Paper>
      </Sequence>
      <Sequence from={beatFrame(SHOWCASE_BEAT)} durationInFrames={beatFrame(END_BEAT) - beatFrame(SHOWCASE_BEAT)} name="Showcase"><Showcase L={L} /></Sequence>
      <Sequence from={beatFrame(END_BEAT)} durationInFrames={beatFrame(TAIL_BEAT) - beatFrame(END_BEAT)} name="End"><EndCard L={L} /></Sequence>
      {/* v5: エンドカードのあとに「困ったら更新情報と使い方」（録画） */}
      <Sequence from={beatFrame(TAIL_BEAT)} name="Tail">
        <Paper>
          <div style={{ position: "absolute", left: 0, right: 0, top: 0 }}><Stripe h={14} /></div>
          {TAIL_SHOTS.map((s, i) => shotSeq(L, s, TAIL_SHOTS[i + 1]?.beat ?? LAST_BEAT, TAIL_BEAT))}
        </Paper>
      </Sequence>
    </AbsoluteFill>
  );
};

/** 録画（または静止画）のショット 1 つ。base = 親の Sequence の頭の拍 */
function shotSeq(L: Layout, s: Shot, next: number, base: number) {
  return (
              <Sequence key={s.beat} from={beatFrame(s.beat) - beatFrame(base)} durationInFrames={beatFrame(next) - beatFrame(s.beat)} name={s.jp || "countdown"}>
                {/* 札はタイトルの裏に回す（先に描くと字幕が上に来る） */}
                {s.ab && <AbBadge L={L} />}
                <Caption L={L} jp={s.jp} en={s.en} delay={s.fx === "flashIn" ? beatFrame(s.beat + 1) - beatFrame(s.beat) : 0}>{s.ev === "url:talk" && <SiteBadges L={L} startBeat={s.beat} />}</Caption>
                <Phone L={L} fx={s.fx}>
                  {s.stills ? (
                    <Stills L={L} shot={s} />
                  ) : s.ab ? (
                    <BeforeAfter L={L} file={s.ab} zoom={L.kind === "wide" ? s.zoomPc : s.zoom}>
                      <Clip kind={L.kind} lang={L.lang} session={s.rec ?? "main"} from={evTime(L.kind, L.lang, s.rec ?? "main", s.ev) + s.off * rate(L.kind, L.lang, s.rec ?? "main")} speed={s.speed} zoom={L.kind === "wide" ? s.zoomPc : s.zoom} still={s.still} />
                    </BeforeAfter>
                  ) : (
                    <Clip kind={L.kind} lang={L.lang} session={s.rec ?? "main"} from={evTime(L.kind, L.lang, s.rec ?? "main", s.ev) + s.off * rate(L.kind, L.lang, s.rec ?? "main")} speed={s.speed} zoom={L.kind === "wide" ? s.zoomPc : s.zoom} still={s.still} />
                  )}
                  {L.kind === "tall" && s.hl && <Highlight L={L} hl={s.hl} />}
                </Phone>
                {s.fx === "flashIn" && <FlashIn />}
                {s.explorer && (() => {
                  // 録画の中で保存した時刻 → このショットの何コマ目か（Clip の再生速度で割る）
                  const sess = s.rec ?? "main", r = rate(L.kind, L.lang, sess) * (s.speed ?? 1);
                  const from = evTime(L.kind, L.lang, sess, s.ev) + s.off * rate(L.kind, L.lang, sess);
                  const at = Math.round(((evTime(L.kind, L.lang, sess, s.explorer.ev) - from) / r) * FPS);
                  const ev = RECORDINGS[L.kind][L.lang][sess].events.find((e) => e.name === s.explorer!.ev) as { file?: string } | undefined;
                  return <Sequence from={at} layout="none"><SavedWindow L={L} file={ev?.file ?? "trackmento-palette.json"} /></Sequence>;
                })()}
              </Sequence>
  );
}
