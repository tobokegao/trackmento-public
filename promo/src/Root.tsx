import { Composition } from "remotion";
import { Promo } from "./Scenes";
import { FPS, DURATION_FRAMES } from "./timeline";

// 縦（9:16）と横（16:9）× 日本語と英語の 4 本。中身はすべて同じ拍割り（timeline.ts）で、
// 録画も字幕も lang に合わせて差し替わる
export const RemotionRoot: React.FC = () => (
  <>
    <Composition id="Promo" component={Promo} durationInFrames={DURATION_FRAMES} fps={FPS} width={1080} height={1920} defaultProps={{ layout: "tall" as const, lang: "ja" as const }} />
    <Composition id="PromoWide" component={Promo} durationInFrames={DURATION_FRAMES} fps={FPS} width={1920} height={1080} defaultProps={{ layout: "wide" as const, lang: "ja" as const }} />
    <Composition id="PromoEn" component={Promo} durationInFrames={DURATION_FRAMES} fps={FPS} width={1080} height={1920} defaultProps={{ layout: "tall" as const, lang: "en" as const }} />
    <Composition id="PromoWideEn" component={Promo} durationInFrames={DURATION_FRAMES} fps={FPS} width={1920} height={1080} defaultProps={{ layout: "wide" as const, lang: "en" as const }} />
  </>
);
