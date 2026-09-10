// 16:9（1920×1080）版。縦の録画をそのまま右に置き、左に字幕。素材・拍・ショット割りは Promo.tsx と共有
import React, { useMemo } from "react";
import { AbsoluteFill, Audio, Img, OffthreadVideo, Sequence, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig, Easing } from "remotion";
import {
  C, STRIPE, beatTime, beatFrame, sec, SHOTS, SHOWCASE_BEAT, END_BEAT, SONG_END, evTime, RATE, useBeatPulse, Paper, Stripe, Wordmark, Shot,
} from "./Promo";

const PHONE_H = 980, PHONE_W = Math.round(PHONE_H * 9 / 16);   // 551
const PHONE_X = 1920 - PHONE_W - 150, PHONE_Y = (1080 - PHONE_H) / 2;

const IntroWide: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { pulse, beat } = useBeatPulse();
  const letters = "TRACKMENTO".split("");
  const taglineIn = spring({ frame: frame - beatFrame(8), fps, config: { damping: 14, stiffness: 120 } });
  const out = interpolate(frame, [beatFrame(28), beatFrame(30)], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.inOut(Easing.cubic) });
  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", transform: `translateY(${-out * 700}px)`, opacity: 1 - out }}>
      <div style={{ display: "flex", gap: 8 }}>
        {letters.map((ch, i) => {
          const s = spring({ frame: frame - beatFrame(Math.round(i * 0.8)), fps, config: { damping: 9, stiffness: 160 } });
          const bump = beat >= 8 && beat % 10 === i ? pulse * 0.15 : 0;
          return <span key={i} style={{ fontFamily: "Silk", fontWeight: 700, fontSize: 150, color: C.ink, lineHeight: 1, display: "inline-block", transform: `translateY(${(1 - s) * 60}px) scale(${s + bump})`, opacity: s }}>{ch}</span>;
        })}
      </div>
      <div style={{ width: 1400, marginTop: 26, position: "relative", height: 20 }}><Stripe y={0} h={20} /></div>
      <div style={{ marginTop: 60, textAlign: "center", transform: `translateY(${(1 - taglineIn) * 40}px)`, opacity: taglineIn }}>
        <div style={{ fontFamily: "Plex", fontWeight: 700, fontSize: 60, color: C.ink, lineHeight: 1.3 }}>好きな曲で、ジャケットのグリッドを。</div>
        <div style={{ fontFamily: "Dot", fontSize: 38, color: C.muted, marginTop: 18, letterSpacing: "0.04em" }}>Your tracks. One grid.</div>
      </div>
    </AbsoluteFill>
  );
};

const CaptionWide: React.FC<{ jp: string; en: string }> = ({ jp, en }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame, fps, config: { damping: 12, stiffness: 170 } });
  return (
    <div style={{ position: "absolute", left: 150, top: 0, bottom: 0, width: 1000, display: "flex", flexDirection: "column", justifyContent: "center" }}>
      <div style={{ display: "inline-block", alignSelf: "flex-start", background: C.ink, color: C.paper, fontFamily: "Plex", fontWeight: 700, fontSize: 84, lineHeight: 1.15, padding: "12px 34px", transform: `translateX(${(1 - s) * -50}px)`, opacity: s }}>{jp}</div>
      <div style={{ fontFamily: "Dot", fontSize: 46, color: C.muted, marginTop: 22, letterSpacing: "0.03em", transform: `translateX(${(1 - s) * -50}px)`, opacity: s }}>{en}</div>
    </div>
  );
};

const PhoneShotWide: React.FC<{ shot: Shot }> = ({ shot }) => {
  const { pulse } = useBeatPulse(0.6);
  return (
    <>
      <CaptionWide jp={shot.jp} en={shot.en} />
      <div style={{ position: "absolute", left: PHONE_X, top: PHONE_Y, width: PHONE_W, height: PHONE_H, border: `5px solid ${C.ink}`, boxShadow: `12px 12px 0 ${C.ink}`, background: C.paper, overflow: "hidden", transform: `scale(${1 + pulse * 0.012})`, transformOrigin: "50% 50%" }}>
        <OffthreadVideo src={staticFile("recordings/session.mp4")} startFrom={sec(evTime(shot.ev) + shot.off * RATE)} playbackRate={RATE} muted style={{ width: "100%", height: "100%", objectFit: "cover", transform: "scale(1.03)" }} />
      </div>
    </>
  );
};

const ShowcaseWide: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { pulse, beat } = useBeatPulse(0.7);
  const s = spring({ frame, fps, config: { damping: 13, stiffness: 90 } });
  const drift = interpolate(frame, [0, (beatTime(END_BEAT) - beatTime(SHOWCASE_BEAT)) * fps], [1.0, 1.05]);
  const color = STRIPE[Math.max(0, beat) % 6];
  const w = Math.round(PHONE_H * 1864 / 3314);
  return (
    <AbsoluteFill style={{ background: color }}>
      <AbsoluteFill style={{ backgroundImage: `radial-gradient(${C.ink}22 1.2px, transparent 1.3px)`, backgroundSize: "14px 14px" }} />
      <div style={{ position: "absolute", left: 1920 - w - 150, top: PHONE_Y, width: w, height: PHONE_H, border: `5px solid ${C.ink}`, boxShadow: `12px 12px 0 ${C.ink}`, overflow: "hidden", background: C.paper, transform: `scale(${s * (drift + pulse * 0.01)})`, transformOrigin: "50% 50%" }}>
        <Img src={staticFile("final.png")} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      </div>
      <div style={{ position: "absolute", left: 150, top: 0, bottom: 0, width: 1000, display: "flex", flexDirection: "column", justifyContent: "center", transform: `translateY(${(1 - s) * -30}px)`, opacity: s }}>
        <div style={{ alignSelf: "flex-start", background: C.ink, color: C.paper, fontFamily: "Plex", fontWeight: 700, fontSize: 96, padding: "12px 36px" }}>できあがり</div>
        <div style={{ fontFamily: "Dot", fontSize: 48, color: C.ink, marginTop: 26 }}>Done in a minute</div>
        <div style={{ fontFamily: "Plex", fontSize: 36, color: C.ink, marginTop: 60, lineHeight: 1.6 }}>1:1 / 16:9 / 9:16、曲名リスト付き。<br />PNG と共有 URL がすぐ出る。</div>
      </div>
    </AbsoluteFill>
  );
};

const EndCardWide: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { pulse } = useBeatPulse();
  const s = spring({ frame, fps, config: { damping: 12, stiffness: 120 } });
  const s2 = spring({ frame: frame - 12, fps, config: { damping: 12, stiffness: 120 } });
  const fade = interpolate(frame / fps + beatTime(END_BEAT), [SONG_END - 0.6, SONG_END + 0.6], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <Paper>
      <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", opacity: fade }}>
        <div style={{ transform: `scale(${s * (1 + pulse * 0.03)})` }}><Wordmark size={140} /></div>
        <div style={{ width: 1400, marginTop: 26, position: "relative", height: 20 }}><Stripe y={0} h={20} /></div>
        <div style={{ marginTop: 56, display: "flex", gap: 40, alignItems: "baseline", opacity: s2, transform: `translateY(${(1 - s2) * 30}px)` }}>
          <div style={{ fontFamily: "Plex", fontWeight: 700, fontSize: 56, color: C.ink }}>あなたの 9 曲は？</div>
          <div style={{ fontFamily: "Dot", fontSize: 40, color: C.muted }}>What are your nine?</div>
        </div>
        <div style={{ marginTop: 60, background: C.ink, color: C.paper, fontFamily: "Silk", fontWeight: 700, fontSize: 48, padding: "18px 44px", letterSpacing: "0.04em", opacity: s2 }}>trackmento.onrender.com</div>
        <div style={{ marginTop: 24, fontFamily: "Dot", fontSize: 32, color: C.muted, opacity: s2 }}>無料・登録なし / Free, no sign-up</div>
      </AbsoluteFill>
    </Paper>
  );
};

export const PromoWide: React.FC = () => {
  const shots = useMemo(() => SHOTS.map((s, i) => ({ s, next: SHOTS[i + 1]?.beat ?? SHOWCASE_BEAT })), []);
  return (
    <AbsoluteFill style={{ background: C.paper }}>
      <Audio src={staticFile("theme.mp3")} />
      <Sequence from={0} durationInFrames={beatFrame(30) + 6} name="Intro"><Paper><IntroWide /></Paper></Sequence>
      <Sequence from={beatFrame(30)} durationInFrames={beatFrame(SHOWCASE_BEAT) - beatFrame(30)} name="Walkthrough">
        <Paper>
          <Stripe y={0} h={14} />
          {shots.map(({ s, next }) => (
            <Sequence key={s.beat} from={beatFrame(s.beat) - beatFrame(30)} durationInFrames={beatFrame(next) - beatFrame(s.beat)} name={s.jp}>
              <PhoneShotWide shot={s} />
            </Sequence>
          ))}
        </Paper>
      </Sequence>
      <Sequence from={beatFrame(SHOWCASE_BEAT)} durationInFrames={beatFrame(END_BEAT) - beatFrame(SHOWCASE_BEAT)} name="Showcase"><ShowcaseWide /></Sequence>
      <Sequence from={beatFrame(END_BEAT)} name="End"><EndCardWide /></Sequence>
    </AbsoluteFill>
  );
};
