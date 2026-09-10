import { Config } from "@remotion/cli/config";

Config.setVideoImageFormat("jpeg");
Config.setOverwriteOutput(true);
Config.setCodec("h264");
Config.setCrf(18);
// フォント読込（loadFont の delayRender）が同時レンダリング中に 28 秒の既定を超えることがある
Config.setDelayRenderTimeoutInMilliseconds(180000);
Config.setConcurrency(4);
