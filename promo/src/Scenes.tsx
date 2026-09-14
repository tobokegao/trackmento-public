// TRACKMENTO 紹介動画。9:16（tall）と 16:9（wide）を同じ部品・同じ拍割りで描く。拍割りは timeline.ts
import React from "react";
import {
  AbsoluteFill, Audio, Freeze, Img, OffthreadVideo, Sequence, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig, Easing,
} from "remotion";
import { loadFont } from "@remotion/fonts";
import {
  FPS, BAR, beatTime, beatFrame, sec, evTime, rate, RECORDINGS, SHOTS, SITES, SITES_EN, BANDWIDTH_ROWS, Shot, Kind, Lang,
  INTRO_END, TIMELAPSE_BEAT, SHOWCASE_BEAT, BANDWIDTH_BEAT, END_BEAT, URL_BEAT, FREE_BEAT, LAST_BEAT, FADE_FROM, timelapseTimes, TIMELAPSE_STEPS,
} from "./timeline";

// ---- フォント（アプリと同じ OFL 同梱フォント） ----
loadFont({ family: "Plex", url: staticFile("fonts/IBMPlexSansJP-Bold.ttf"), weight: "700" });
loadFont({ family: "Plex", url: staticFile("fonts/IBMPlexSansJP-Regular.ttf"), weight: "400" });
loadFont({ family: "Silk", url: staticFile("fonts/Silkscreen-Bold.ttf"), weight: "700" });
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
  tall: { kind: "tall", W: 1080, H: 1920, phone: { x: 108, y: 330, w: 864, h: 1536 }, jp: 62, en: 36, mark: 112, tag: 64, sub: 40 },
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
const Stripe: React.FC<{ h?: number; width?: number | string }> = ({ h = 14, width = "100%" }) => {
  const { beat, pulse } = useBeatPulse();
  return (
    <div style={{ width, height: h, display: "flex" }}>
      {STRIPE.map((c, i) => <div key={c} style={{ flex: 1, background: c, transform: `scaleY(${beat >= 0 && beat % 6 === i ? 1 + pulse * 1.6 : 1})`, transformOrigin: "bottom" }} />)}
    </div>
  );
};

const Wordmark: React.FC<{ size: number }> = ({ size }) => (
  <div style={{ fontFamily: "Silk", fontWeight: 700, fontSize: size, letterSpacing: "0.06em", color: C.ink, lineHeight: 1 }}>TRACKMENTO</div>
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
          return <span key={i} style={{ fontFamily: "Silk", fontWeight: 700, fontSize: L.kind === "tall" ? 118 : 150, color: C.ink, lineHeight: 1, display: "inline-block", transform: `translateY(${(1 - s) * 60}px)`, opacity: s }}>{ch}</span>;
        })}
      </div>
      <div style={{ marginTop: 24, opacity: logoIn, transform: `scaleX(${logoIn})` }}><Stripe h={18} width={stripeW} /></div>
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
        return <span key={name} style={{ fontFamily: "Plex", fontWeight: 700, fontSize: L.kind === "tall" ? 23 : 26, color: C.ink, border: `3px solid ${C.ink}`, background: STRIPE[i % 6], padding: "2px 10px", display: "inline-block", transform: `scale(${s})`, opacity: s }}>{name}</span>;
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
  const switchAt = beatFrame(BAR) - beatFrame(0);   // 1 小節で切り替える
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
      <div style={{ position: "absolute", left: tall ? 24 : 28, bottom: tall ? 24 : 28,
        background: before ? C.muted : C.vermilion, color: C.paper, fontFamily: "Silk", fontWeight: 700,
        fontSize: tall ? 40 : 34, padding: "8px 20px", border: `4px solid ${C.ink}`,
        transform: `translateY(${(1 - s) * 30}px) scale(${0.85 + s * 0.15})`, opacity: s }}>
        {before ? "BEFORE" : "NOW"}
      </div>
    </>
  );
};

/** 録画の一部を枠線で強調（拍で脈打つ） */
const Highlight: React.FC<{ L: Layout; hl: NonNullable<Shot["hl"]> }> = ({ L, hl }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { pulse } = useBeatPulse(0.8);
  const s = spring({ frame, fps, config: { damping: 12, stiffness: 160 } });
  const pad = 6 + pulse * 6;
  return (
    <div style={{ position: "absolute", left: `${hl.x * 100}%`, top: `${hl.y * 100}%`, width: `${hl.w * 100}%`, height: `${hl.h * 100}%`, boxSizing: "border-box",
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

// ---- タイムラプス（1 小節に 16 コマ） ----
const Timelapse: React.FC<{ L: Layout }> = ({ L }) => {
  const times = timelapseTimes(L.kind, L.lang);
  const total = beatFrame(TIMELAPSE_BEAT + BAR) - beatFrame(TIMELAPSE_BEAT);
  const per = total / TIMELAPSE_STEPS;
  return (
    <>
      <Caption L={L} jp="画像完成まで" en="Start to finish" />
      <Phone L={L}>
        {times.map((t, i) => (
          <Sequence key={i} from={Math.round(i * per)} durationInFrames={Math.ceil(per) + 1} layout="none">
            <OffthreadVideo src={staticFile(RECORDINGS[L.kind][L.lang].main.src)} startFrom={sec(t)} playbackRate={rate(L.kind, L.lang, "main")} muted style={{ width: "100%", height: "100%", objectFit: "cover", transform: "scale(1.03)" }} />
          </Sequence>
        ))}
      </Phone>
    </>
  );
};

// ---- できあがり（2 小節） ----
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
  return (
    <AbsoluteFill style={{ background: color }}>
      <AbsoluteFill style={{ backgroundImage: `radial-gradient(${C.ink}22 1.2px, transparent 1.3px)`, backgroundSize: "14px 14px" }} />
      <div style={{ position: "absolute", ...img, border: `6px solid ${C.ink}`, boxShadow: `16px 16px 0 ${C.ink}`, overflow: "hidden", background: C.paper, transform: `scale(${s * (drift + pulse * 0.01)})`, transformOrigin: "50% 50%" }}>
        <Img src={staticFile(RECORDINGS[L.kind][L.lang].main.final)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
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

// ---- エンドカード（あなたの 9 曲は？ 2 小節 → URL 1 小節 → 無料 1 小節） ----
const EndCard: React.FC<{ L: Layout }> = ({ L }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { pulse } = useBeatPulse();
  const s = spring({ frame, fps, config: { damping: 12, stiffness: 120 } });
  const s2 = spring({ frame: frame - 10, fps, config: { damping: 12, stiffness: 120 } });
  const sUrl = spring({ frame: frame - (beatFrame(URL_BEAT) - beatFrame(END_BEAT)), fps, config: { damping: 12, stiffness: 140 } });
  const sFree = spring({ frame: frame - (beatFrame(FREE_BEAT) - beatFrame(END_BEAT)), fps, config: { damping: 12, stiffness: 140 } });
  const fade = interpolate(frame, [beatFrame(LAST_BEAT) - beatFrame(END_BEAT) - 6, beatFrame(LAST_BEAT) - beatFrame(END_BEAT) + 10], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const tall = L.kind === "tall";
  return (
    <Paper>
      <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", opacity: fade }}>
        <div style={{ transform: `scale(${s * (1 + pulse * 0.03)})` }}><Wordmark size={L.mark} /></div>
        <div style={{ marginTop: 24 }}><Stripe h={18} width={tall ? 1000 : 1400} /></div>
        <div style={{ marginTop: tall ? 80 : 56, display: "flex", flexDirection: tall ? "column" : "row", gap: tall ? 12 : 40, alignItems: tall ? "center" : "baseline", opacity: s2, transform: `translateY(${(1 - s2) * 30}px)` }}>
          {L.lang === "ja" && <div style={{ fontFamily: "Plex", fontWeight: 700, fontSize: tall ? 54 : 56, color: C.ink }}>あなたの 9 曲は？</div>}
          <div style={{ fontFamily: "Dot", fontSize: L.lang === "ja" ? (tall ? 38 : 40) : (tall ? 50 : 52), color: L.lang === "ja" ? C.muted : C.ink }}>What are your nine?</div>
        </div>
        <div style={{ marginTop: tall ? 90 : 60, background: C.ink, color: C.paper, fontFamily: "Silk", fontWeight: 700, fontSize: tall ? 44 : 48, padding: "18px 40px", letterSpacing: "0.04em", opacity: sUrl, transform: `scale(${0.8 + sUrl * 0.2})` }}>trackmento.onrender.com</div>
        <div style={{ marginTop: 28, fontFamily: "Dot", fontSize: 32, color: C.muted, opacity: sFree, transform: `translateY(${(1 - sFree) * 20}px)` }}>{L.lang === "ja" ? "無料・登録なし / Free, no sign-up" : "Free, no sign-up"}</div>
      </AbsoluteFill>
    </Paper>
  );
};

// ---- ⑥ 転送量削減（1 小節。録画ではなく数字を出す） ----
const Bandwidth: React.FC<{ L: Layout }> = ({ L }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const beatLen = beatFrame(1) - beatFrame(0);
  const tall = L.kind === "tall";
  const s = spring({ frame, fps, config: { damping: 13, stiffness: 140 } });
  return (
    <Paper>
      <div style={{ position: "absolute", left: 0, right: 0, top: 0 }}><Stripe h={14} /></div>
      <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", padding: tall ? "0 70px" : "0 220px" }}>
        <div style={{ background: C.ink, color: C.paper, fontFamily: L.lang === "ja" ? "Plex" : "Dot", fontWeight: 700, fontSize: tall ? 52 : 54, padding: "10px 28px", transform: `translateY(${(1 - s) * -24}px)`, opacity: s }}>
          {L.lang === "ja" ? "重たくなくなりました" : "And it got lighter"}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: tall ? 18 : 14, marginTop: tall ? 54 : 40, width: "100%" }}>
          {BANDWIDTH_ROWS.map((r, i) => {
            // 1 行ずつ拍に乗せて出す
            const k = spring({ frame: frame - Math.round(beatLen * (i * 0.25 + 0.25)), fps, config: { damping: 12, stiffness: 220 } });
            return (
              <div key={r.jp} style={{ display: "flex", alignItems: "baseline", gap: tall ? 16 : 24, transform: `translateX(${(1 - k) * -30}px)`, opacity: k }}>
                <div style={{ fontFamily: L.lang === "ja" ? "Plex" : "Dot", fontWeight: 700, fontSize: tall ? 34 : 36, color: C.ink, flex: 1 }}>{L.lang === "ja" ? r.jp : r.en}</div>
                <div style={{ fontFamily: "Silk", fontWeight: 700, fontSize: tall ? 30 : 32, color: C.muted, textDecoration: "line-through" }}>{r.from}</div>
                <div style={{ fontFamily: "Silk", fontWeight: 700, fontSize: tall ? 34 : 36, color: C.paper, background: STRIPE[i % 6], padding: "2px 12px", border: `3px solid ${C.ink}` }}>{r.to}</div>
              </div>
            );
          })}
        </div>
        <div style={{ fontFamily: "Dot", fontSize: tall ? 30 : 32, color: C.muted, marginTop: tall ? 46 : 34, opacity: spring({ frame: frame - beatLen * 2, fps, config: { damping: 12, stiffness: 160 } }) }}>
          {L.lang === "ja" ? "画質はそのまま" : "Same image quality"}
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
      <Audio src={staticFile("sherbet.mp3")} volume={(f) => interpolate(f, [beatFrame(FADE_FROM), beatFrame(LAST_BEAT) + 6], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })} />
      <Sequence from={0} durationInFrames={beatFrame(INTRO_END)} name="Intro"><Paper><Intro L={L} /></Paper></Sequence>

      <Sequence from={beatFrame(INTRO_END)} durationInFrames={flowEnd - beatFrame(INTRO_END)} name="Walkthrough">
        <Paper>
          <div style={{ position: "absolute", left: 0, right: 0, top: 0 }}><Stripe h={14} /></div>
          {SHOTS.map((s, i) => {
            const next = SHOTS[i + 1]?.beat ?? TIMELAPSE_BEAT;
            return (
              <Sequence key={s.beat} from={beatFrame(s.beat) - beatFrame(INTRO_END)} durationInFrames={beatFrame(next) - beatFrame(s.beat)} name={s.jp || "countdown"}>
                <Caption L={L} jp={s.jp} en={s.en} delay={s.fx === "flashIn" ? beatFrame(s.beat + 1) - beatFrame(s.beat) : 0}>{s.ev === "url:talk" && <SiteBadges L={L} startBeat={s.beat} />}</Caption>
                <Phone L={L} fx={s.fx}>
                  {s.ab ? (
                    <BeforeAfter L={L} file={s.ab} zoom={L.kind === "wide" ? s.zoomPc : s.zoom}>
                      <Clip kind={L.kind} lang={L.lang} session={s.rec ?? "main"} from={evTime(L.kind, L.lang, s.rec ?? "main", s.ev) + s.off * rate(L.kind, L.lang, s.rec ?? "main")} speed={s.speed} zoom={L.kind === "wide" ? s.zoomPc : s.zoom} still={s.still} />
                    </BeforeAfter>
                  ) : (
                    <Clip kind={L.kind} lang={L.lang} session={s.rec ?? "main"} from={evTime(L.kind, L.lang, s.rec ?? "main", s.ev) + s.off * rate(L.kind, L.lang, s.rec ?? "main")} speed={s.speed} zoom={L.kind === "wide" ? s.zoomPc : s.zoom} still={s.still} />
                  )}
                  {L.kind === "tall" && s.hl && <Highlight L={L} hl={s.hl} />}
                </Phone>
                {s.fx === "flashIn" && <FlashIn />}
              </Sequence>
            );
          })}
        </Paper>
      </Sequence>

      <Sequence from={beatFrame(BANDWIDTH_BEAT)} durationInFrames={beatFrame(BANDWIDTH_BEAT + BAR) - beatFrame(BANDWIDTH_BEAT)} name="Bandwidth"><Bandwidth L={L} /></Sequence>

      <Sequence from={beatFrame(TIMELAPSE_BEAT)} durationInFrames={beatFrame(SHOWCASE_BEAT) - beatFrame(TIMELAPSE_BEAT)} name="Timelapse">
        <Paper><div style={{ position: "absolute", left: 0, right: 0, top: 0 }}><Stripe h={14} /></div><Timelapse L={L} /></Paper>
      </Sequence>
      <Sequence from={beatFrame(SHOWCASE_BEAT)} durationInFrames={beatFrame(END_BEAT) - beatFrame(SHOWCASE_BEAT)} name="Showcase"><Showcase L={L} /></Sequence>
      <Sequence from={beatFrame(END_BEAT)} name="End"><EndCard L={L} /></Sequence>
    </AbsoluteFill>
  );
};
