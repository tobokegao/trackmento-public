import { Composition } from "remotion";
import { Promo, FPS, DURATION_FRAMES } from "./Promo";
import { PromoWide } from "./Wide";

export const RemotionRoot: React.FC = () => (
  <>
    <Composition id="Promo" component={Promo} durationInFrames={DURATION_FRAMES} fps={FPS} width={1080} height={1920} />
    <Composition id="PromoWide" component={PromoWide} durationInFrames={DURATION_FRAMES} fps={FPS} width={1920} height={1080} />
  </>
);
