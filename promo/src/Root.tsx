import { Composition } from "remotion";
import { Promo } from "./Scenes";
import { FPS, DURATION_FRAMES } from "./timeline";
import { XClip, xclipMetadata } from "./XClip";

// 縦（9:16）と横（16:9）× 日本語と英語の 4 本。中身はすべて同じ拍割り（timeline.ts）で、
// 録画も字幕も lang に合わせて差し替わる
export const RemotionRoot: React.FC = () => (
  <>
    <Composition id="Promo" component={Promo} durationInFrames={DURATION_FRAMES} fps={FPS} width={1080} height={1920} defaultProps={{ layout: "tall" as const, lang: "ja" as const }} />
    <Composition id="PromoWide" component={Promo} durationInFrames={DURATION_FRAMES} fps={FPS} width={1920} height={1080} defaultProps={{ layout: "wide" as const, lang: "ja" as const }} />
    <Composition id="PromoEn" component={Promo} durationInFrames={DURATION_FRAMES} fps={FPS} width={1080} height={1920} defaultProps={{ layout: "tall" as const, lang: "en" as const }} />
    <Composition id="PromoWideEn" component={Promo} durationInFrames={DURATION_FRAMES} fps={FPS} width={1920} height={1080} defaultProps={{ layout: "wide" as const, lang: "en" as const }} />
    {/* X に載せる 1 機能 1 本の短い動画（render_x.mjs が id を渡して 1 本ずつ書き出す。長さは素材から決まる） */}
    <Composition id="XClip" component={XClip} calculateMetadata={xclipMetadata} durationInFrames={1} fps={30} width={1280} height={720} defaultProps={{ id: "color-sort" }} />
  </>
);
