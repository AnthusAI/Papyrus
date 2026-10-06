export type PreviewStageFitInput = {
  containerHeight: number;
  containerWidth: number;
  stageHeight: number;
  stageWidth: number;
};

export type PreviewStageFit = {
  height: number;
  scale: number;
  width: number;
};

export function computePreviewStageFit(input: PreviewStageFitInput): PreviewStageFit {
  const stageWidth = input.stageWidth > 0 ? input.stageWidth : 1280;
  const stageHeight = input.stageHeight > 0 ? input.stageHeight : 720;
  const containerWidth = input.containerWidth > 0 ? input.containerWidth : stageWidth;
  const containerHeight = input.containerHeight > 0 ? input.containerHeight : stageHeight;

  const scale = Math.min(containerWidth / stageWidth, containerHeight / stageHeight);
  const safeScale = Number.isFinite(scale) && scale > 0 ? scale : 1;

  return {
    height: stageHeight * safeScale,
    scale: safeScale,
    width: stageWidth * safeScale,
  };
}
