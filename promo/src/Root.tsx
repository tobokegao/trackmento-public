import { Composition } from "remotion";
import { Promo } from "./Scenes";
import { FPS, DURATION_FRAMES } from "./timeline";

export const RemotionRoot: React.FC = () => (
  <>
    <Composition id="Promo" component={Promo} durationInFrames={DURATION_FRAMES} fps={FPS} width={1080} height={1920} defaultProps={{ layout: "tall" as const }} />
    <Composition id="PromoWide" component={Promo} durationInFrames={DURATION_FRAMES} fps={FPS} width={1920} height={1080} defaultProps={{ layout: "wide" as const }} />
  </>
);
