// TRACKMENTO 紹介動画（9:16）。Dogsled Race Replay Theme（129.2 BPM）の拍に合わせて、
// Playwright で録った操作（public/recordings/session.mp4）を切り替える。
// 拍の時刻は src/beats.json（librosa の beat_track）。ショットの開始は必ず拍の頭。
import React, { useMemo } from "react";
import {
  AbsoluteFill, Audio, Img, OffthreadVideo, Sequence, interpolate, spring, staticFile,
  useCurrentFrame, useVideoConfig, Easing,
} from "remotion";
import { loadFont } from "@remotion/fonts";
import beatsJson from "./beats.json";
import eventsJson from "../public/recordings/events.json";

export const FPS = 30;
const BEATS: number[] = beatsJson.beats;
export const SONG_END = 73.6;                                   // 曲が鳴り終わる秒
export const DURATION_FRAMES = Math.ceil(beatsJson.duration * FPS);

// ---- フォント（アプリと同じ OFL 同梱フォント） ----
loadFont({ family: "Plex", url: staticFile("fonts/IBMPlexSansJP-Bold.ttf"), weight: "700" });
loadFont({ family: "Plex", url: staticFile("fonts/IBMPlexSansJP-Regular.ttf"), weight: "400" });
loadFont({ family: "Silk", url: staticFile("fonts/Silkscreen-Bold.ttf"), weight: "700" });
loadFont({ family: "Dot", url: staticFile("fonts/DotGothic16-Regular.ttf"), weight: "400" });

// ---- 色（frontend/index.html のトークンと同じ系統） ----
export const C = {
  paper: "#f5f4f0", paper2: "#ebe9e3", ink: "#1b1d24", ink2: "#2b2e38", muted: "#5a5e6a", rule: "#b4b7c1",
  mustard: "#e6b731", cerulean: "#008bc7", vermilion: "#e5462c", lavender: "#af9ee4", mint: "#80e2b9", pink: "#f594c3",
};
export const STRIPE = [C.mustard, C.cerulean, C.vermilion, C.lavender, C.mint, C.pink];

export const beatTime = (i: number) => BEATS[Math.min(i, BEATS.length - 1)];
export const beatFrame = (i: number) => Math.round(beatTime(i) * FPS);
export const sec = (s: number) => Math.round(s * FPS);

/** 直前の拍からの経過（0→1 で減衰）。拍の頭で 1 */
export function useBeatPulse(decayBeats = 1) {
  const frame = useCurrentFrame();
  const t = frame / FPS;
  let last = -1, next = 1e9;
  for (let i = 0; i < BEATS.length; i++) { if (BEATS[i] <= t) last = i; else { next = BEATS[i]; break; } }
  if (last < 0) return { pulse: 0, beat: -1 };
  const len = (next - BEATS[last]) * decayBeats;
  const p = Math.max(0, 1 - (t - BEATS[last]) / len);
  return { pulse: p * p, beat: last };
}

// ---- ショット定義（録画のどの操作の何秒前から、何拍分、どの字幕で見せるか） ----
// from は record.mjs が書く events.json の操作名 + オフセット秒。録り直しても時刻を手で直さなくてよい
const EVENTS: { t: number; v?: number; name: string }[] = eventsJson as never;
// Playwright の動画は実時間より 1 割ほど遅い（フレーム落ち分が引き延ばされる）。最後の操作の v/t で率を出し、再生速度で戻す
const _last = [...EVENTS].reverse().find((e) => e.v !== undefined && e.t > 10);
export const RATE = _last ? (_last.v! - (EVENTS[0].v ?? 0)) / (_last.t - EVENTS[0].t) : 1;
export const evTime = (name: string) => {
  const e = EVENTS.find((x) => x.name === name);
  if (!e) throw new Error(`events.json に ${name} がない`);
  return e.v ?? e.t;   // v = 動画内の時刻（scan.py がマーカーから付ける）。無ければ実時間
};
export type Shot = { beat: number; len: number; ev: string; off: number; jp: string; en: string };
export const SHOTS: Shot[] = [
  { beat: 30, len: 4, ev: "title-focus", off: -0.10, jp: "まずタイトル", en: "Name your grid" },
  { beat: 34, len: 2, ev: "title-done", off: -0.05, jp: "曲を探す", en: "Find tracks" },
  { beat: 36, len: 4, ev: "search:chikamichi", off: -1.30, jp: "曲名で検索", en: "Search by title / artist" },
  { beat: 40, len: 2, ev: "add:chikamichi", off: -0.30, jp: "タップで配置", en: "Tap to place" },
  { beat: 42, len: 2, ev: "search:vagabond", off: -0.33, jp: "曲名で検索", en: "Search by title / artist" },
  { beat: 44, len: 2, ev: "add:vagabond", off: -0.30, jp: "タップで配置", en: "Tap to place" },
  { beat: 46, len: 4, ev: "url:talk", off: -0.70, jp: "URL を貼るだけ", en: "Or paste a URL — YouTube" },
  { beat: 50, len: 3, ev: "url:10-10-10", off: -0.30, jp: "URL を貼るだけ", en: "niconico" },
  { beat: 53, len: 3, ev: "manual:mitsuami", off: -0.34, jp: "手持ちの画像も", en: "Your own artwork" },
  { beat: 56, len: 3, ev: "url:birdbrain", off: -0.30, jp: "URL を貼るだけ", en: "Bandcamp" },
  { beat: 59, len: 3, ev: "url:worldwidesuperstar", off: -0.30, jp: "URL を貼るだけ", en: "SoundCloud" },
  { beat: 62, len: 3, ev: "manual:runaway", off: -0.30, jp: "手持ちの画像も", en: "Your own artwork" },
  { beat: 65, len: 3, ev: "search:ilovelove", off: -0.30, jp: "MusicBrainz でも", en: "iTunes / MusicBrainz / Discogs" },
  { beat: 68, len: 4, ev: "add:ilovelove", off: 0.05, jp: "9 曲そろった", en: "All nine in" },
  { beat: 72, len: 3, ev: "select:1", off: -0.15, jp: "タップで入れ替え", en: "Tap two cells to swap" },
  { beat: 75, len: 3, ev: "select:2", off: -0.15, jp: "タップで入れ替え", en: "Tap two cells to swap" },
  { beat: 78, len: 3, ev: "select:3", off: -0.15, jp: "タップで入れ替え", en: "Tap two cells to swap" },
  { beat: 81, len: 3, ev: "select:4", off: -0.15, jp: "タップで入れ替え", en: "Tap two cells to swap" },
  { beat: 84, len: 3, ev: "select:5", off: -0.15, jp: "タップで入れ替え", en: "Tap two cells to swap" },
  { beat: 87, len: 3, ev: "select:6", off: -0.15, jp: "タップで入れ替え", en: "Tap two cells to swap" },
  { beat: 90, len: 3, ev: "select:7", off: -0.15, jp: "タップで入れ替え", en: "Tap two cells to swap" },
  { beat: 93, len: 3, ev: "reorder-done", off: -0.30, jp: "並び完成", en: "Done" },
  { beat: 96, len: 2, ev: "open-options", off: -0.15, jp: "出力オプション", en: "Output options" },
  { beat: 98, len: 2, ev: "ratio:9:16", off: -0.15, jp: "9:16 ストーリーズ", en: "1:1 / 16:9 / 9:16" },
  { beat: 100, len: 1, ev: "bg:cerulean", off: -0.12, jp: "背景色", en: "Pick a color" },
  { beat: 101, len: 1, ev: "bg:pink", off: -0.12, jp: "背景色", en: "Pick a color" },
  { beat: 102, len: 1, ev: "bg:mustard", off: -0.12, jp: "背景色", en: "Pick a color" },
  { beat: 103, len: 3, ev: "bg:mustard", off: 0.20, jp: "背景色", en: "Pick a color" },
  { beat: 106, len: 4, ev: "share", off: -0.20, jp: "トラックを共有", en: "Share" },
  { beat: 110, len: 6, ev: "share-ready", off: -0.14, jp: "PNG と共有 URL", en: "A PNG and a link" },
  { beat: 116, len: 9, ev: "share-page", off: 0.00, jp: "共有ページ", en: "Open the share page" },
];
export const SHOWCASE_BEAT = 125;   // 完成画像を見せ始める拍
export const END_BEAT = 145;        // エンドカード

// ---- 背景（紙＋ハーフトーン） ----
export const Paper: React.FC<{ children?: React.ReactNode }> = ({ children }) => (
  <AbsoluteFill style={{ background: C.paper }}>
    <AbsoluteFill style={{
      backgroundImage: `radial-gradient(${C.ink}12 1.2px, transparent 1.3px)`, backgroundSize: "14px 14px", opacity: 0.9,
    }} />
    {children}
  </AbsoluteFill>
);

// 6 色の帯。拍ごとに 1 色ずつ「点灯」する
export const Stripe: React.FC<{ y: number; h?: number }> = ({ y, h = 14 }) => {
  const { beat, pulse } = useBeatPulse();
  return (
    <div style={{ position: "absolute", left: 0, right: 0, top: y, height: h, display: "flex" }}>
      {STRIPE.map((c, i) => {
        const lit = beat >= 0 && beat % 6 === i;
        return <div key={c} style={{ flex: 1, background: c, transform: `scaleY(${lit ? 1 + pulse * 1.6 : 1})`, transformOrigin: "bottom" }} />;
      })}
    </div>
  );
};

// ---- ワードマーク ----
export const Wordmark: React.FC<{ size: number; color?: string }> = ({ size, color = C.ink }) => (
  <div style={{ fontFamily: "Silk", fontWeight: 700, fontSize: size, letterSpacing: "0.06em", color, lineHeight: 1 }}>TRACKMENTO</div>
);

// ---- イントロ（0 〜 14 秒） ----
const Intro: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { pulse, beat } = useBeatPulse();
  const letters = "TRACKMENTO".split("");
  const taglineIn = spring({ frame: frame - beatFrame(8), fps, config: { damping: 14, stiffness: 120 } });
  const out = interpolate(frame, [beatFrame(28), beatFrame(30)], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.inOut(Easing.cubic) });
  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", transform: `translateY(${-out * 900}px)`, opacity: 1 - out }}>
      <div style={{ display: "flex", gap: 6 }}>
        {letters.map((ch, i) => {
          const s = spring({ frame: frame - beatFrame(Math.round(i * 0.8)), fps, config: { damping: 9, stiffness: 160 } });
          const bump = beat >= 8 && beat % 10 === i ? pulse * 0.15 : 0;
          return (
            <span key={i} style={{
              fontFamily: "Silk", fontWeight: 700, fontSize: 118, color: C.ink, lineHeight: 1,
              display: "inline-block", transform: `translateY(${(1 - s) * 60}px) scale(${s + bump})`, opacity: s,
            }}>{ch}</span>
          );
        })}
      </div>
      <div style={{ width: 1000, marginTop: 24, position: "relative", height: 18 }}><Stripe y={0} h={18} /></div>
      <div style={{ marginTop: 90, textAlign: "center", transform: `translateY(${(1 - taglineIn) * 40}px)`, opacity: taglineIn }}>
        <div style={{ fontFamily: "Plex", fontWeight: 700, fontSize: 64, color: C.ink, lineHeight: 1.3 }}>好きな曲で、<br />ジャケットのグリッドを。</div>
        <div style={{ fontFamily: "Dot", fontSize: 40, color: C.muted, marginTop: 22, letterSpacing: "0.04em" }}>Your tracks. One grid.</div>
      </div>
    </AbsoluteFill>
  );
};

// ---- 操作ショット（スマホ枠＋字幕） ----
const PHONE_W = 864, PHONE_H = 1536;          // 1080×1920 を 0.8 倍
export const Caption: React.FC<{ jp: string; en: string; startFrame: number }> = ({ jp, en, startFrame }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame: frame - startFrame, fps, config: { damping: 12, stiffness: 170 } });
  return (
    <div style={{ position: "absolute", left: 60, right: 60, top: 96, height: 210, display: "flex", flexDirection: "column", justifyContent: "flex-end" }}>
      <div style={{ display: "inline-block", alignSelf: "flex-start", background: C.ink, color: C.paper, fontFamily: "Plex", fontWeight: 700, fontSize: 62, lineHeight: 1.15, padding: "10px 26px", transform: `translateX(${(1 - s) * -40}px)`, opacity: s }}>{jp}</div>
      <div style={{ fontFamily: "Dot", fontSize: 36, color: C.muted, marginTop: 14, letterSpacing: "0.03em", transform: `translateX(${(1 - s) * -40}px)`, opacity: s }}>{en}</div>
    </div>
  );
};

const PhoneShot: React.FC<{ shot: Shot; nextBeat: number }> = ({ shot }) => {
  const { pulse } = useBeatPulse(0.6);
  const scale = 1 + pulse * 0.012;
  return (
    <>
      <Caption jp={shot.jp} en={shot.en} startFrame={0} />
      <div style={{
        position: "absolute", left: (1080 - PHONE_W) / 2, top: 330, width: PHONE_W, height: PHONE_H,
        border: `6px solid ${C.ink}`, boxShadow: `14px 14px 0 ${C.ink}`, background: C.paper, overflow: "hidden",
        transform: `scale(${scale})`, transformOrigin: "50% 40%",
      }}>
        <OffthreadVideo src={staticFile("recordings/session.mp4")} startFrom={sec(evTime(shot.ev) + shot.off * RATE)} playbackRate={RATE} muted style={{ width: "100%", height: "100%", objectFit: "cover", transform: "scale(1.03)" }} />
      </div>
    </>
  );
};

// ---- 完成画像のショーケース ----
const Showcase: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { pulse, beat } = useBeatPulse(0.7);
  const s = spring({ frame, fps, config: { damping: 13, stiffness: 90 } });
  const drift = interpolate(frame, [0, (beatTime(END_BEAT) - beatTime(SHOWCASE_BEAT)) * fps], [1.0, 1.06]);
  const color = STRIPE[Math.max(0, beat) % 6];
  return (
    <AbsoluteFill style={{ background: color }}>
      <AbsoluteFill style={{ backgroundImage: `radial-gradient(${C.ink}22 1.2px, transparent 1.3px)`, backgroundSize: "14px 14px" }} />
      <div style={{
        position: "absolute", left: 90, top: 200, width: 900, height: 1600, border: `6px solid ${C.ink}`, boxShadow: `16px 16px 0 ${C.ink}`, overflow: "hidden", background: C.paper,
        transform: `scale(${s * (drift + pulse * 0.01)})`, transformOrigin: "50% 50%",
      }}>
        <Img src={staticFile("final.png")} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      </div>
      <div style={{ position: "absolute", left: 90, top: 96, background: C.ink, color: C.paper, fontFamily: "Plex", fontWeight: 700, fontSize: 56, padding: "8px 24px", transform: `translateY(${(1 - s) * -30}px)`, opacity: s }}>できあがり</div>
      <div style={{ position: "absolute", right: 90, top: 110, fontFamily: "Dot", fontSize: 36, color: C.ink, opacity: s }}>Done in a minute</div>
    </AbsoluteFill>
  );
};

// ---- エンドカード ----
const EndCard: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { pulse } = useBeatPulse();
  const s = spring({ frame, fps, config: { damping: 12, stiffness: 120 } });
  const s2 = spring({ frame: frame - 12, fps, config: { damping: 12, stiffness: 120 } });
  const fade = interpolate(frame / fps + beatTime(END_BEAT), [SONG_END - 0.6, SONG_END + 0.6], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <Paper>
      <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", opacity: fade }}>
        <div style={{ transform: `scale(${s * (1 + pulse * 0.03)})` }}><Wordmark size={112} /></div>
        <div style={{ width: 1000, marginTop: 24, position: "relative", height: 18 }}><Stripe y={0} h={18} /></div>
        <div style={{ marginTop: 80, fontFamily: "Plex", fontWeight: 700, fontSize: 54, color: C.ink, opacity: s2, transform: `translateY(${(1 - s2) * 30}px)` }}>あなたの 9 曲は？</div>
        <div style={{ marginTop: 12, fontFamily: "Dot", fontSize: 38, color: C.muted, opacity: s2 }}>What are your nine?</div>
        <div style={{ marginTop: 90, background: C.ink, color: C.paper, fontFamily: "Silk", fontWeight: 700, fontSize: 44, padding: "18px 40px", letterSpacing: "0.04em", opacity: s2 }}>trackmento.onrender.com</div>
        <div style={{ marginTop: 28, fontFamily: "Dot", fontSize: 32, color: C.muted, opacity: s2 }}>無料・登録なし / Free, no sign-up</div>
      </AbsoluteFill>
    </Paper>
  );
};

// ---- 本体 ----
export const Promo: React.FC = () => {
  const shots = useMemo(() => SHOTS.map((s, i) => ({ s, next: SHOTS[i + 1]?.beat ?? SHOWCASE_BEAT })), []);
  return (
    <AbsoluteFill style={{ background: C.paper }}>
      <Audio src={staticFile("theme.mp3")} />
      <Sequence from={0} durationInFrames={beatFrame(30) + 6} name="Intro">
        <Paper><Intro /></Paper>
      </Sequence>
      <Sequence from={beatFrame(30)} durationInFrames={beatFrame(SHOWCASE_BEAT) - beatFrame(30)} name="Walkthrough">
        <Paper>
          <Stripe y={0} h={14} />
          {shots.map(({ s, next }) => (
            <Sequence key={s.beat} from={beatFrame(s.beat) - beatFrame(30)} durationInFrames={beatFrame(next) - beatFrame(s.beat)} name={s.jp}>
              <PhoneShot shot={s} nextBeat={next} />
            </Sequence>
          ))}
        </Paper>
      </Sequence>
      <Sequence from={beatFrame(SHOWCASE_BEAT)} durationInFrames={beatFrame(END_BEAT) - beatFrame(SHOWCASE_BEAT)} name="Showcase">
        <Showcase />
      </Sequence>
      <Sequence from={beatFrame(END_BEAT)} name="End">
        <EndCard />
      </Sequence>
    </AbsoluteFill>
  );
};
