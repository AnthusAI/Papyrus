export type VideoPreload = "none" | "metadata";

export type VideoLoadingPlan = {
  attachSource: boolean;
  preload: VideoPreload;
};

export type VideoLoadingInput = {
  hasHydrated: boolean;
  isNearViewport: boolean;
  hasPoster: boolean;
};

export function planVideoLoading({ hasHydrated, isNearViewport, hasPoster }: VideoLoadingInput): VideoLoadingPlan {
  const attachSource = hasHydrated && isNearViewport;
  const preload: VideoPreload = attachSource && !hasPoster ? "metadata" : "none";
  return { attachSource, preload };
}

export function videoElementKey(attachSource: boolean, resolvedSource: string): string {
  return attachSource ? resolvedSource : "unattached";
}
