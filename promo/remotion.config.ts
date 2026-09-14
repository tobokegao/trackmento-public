import { Config } from "@remotion/cli/config";

Config.setVideoImageFormat("jpeg");
Config.setOverwriteOutput(true);
Config.setCodec("h264");
// 音だけ書き出すとき（mp3 / wav）は CRF を渡すと怒られるので、映像のときだけ設定する
if (!process.argv.some((a) => a.includes("mp3") || a.includes("wav"))) {
  Config.setCrf(18);
}
// フォント読込（loadFont の delayRender）が同時レンダリング中に 28 秒の既定を超えることがある
Config.setDelayRenderTimeoutInMilliseconds(180000);
Config.setConcurrency(4);
