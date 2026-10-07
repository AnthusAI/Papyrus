export type FontFaceSetLike = {
  load(font: string): Promise<unknown>;
  ready: Promise<unknown>;
  addEventListener(type: string, listener: () => void): void;
  removeEventListener(type: string, listener: () => void): void;
};

export type WatchBrandFontsOptions = {
  fontFaceSet: FontFaceSetLike | undefined;
  families: string[];
  clearMeasurementCaches: () => void;
  onFontsSettled: () => void;
};

/**
 * Clears Pretext measurement caches and then notifies the caller every time
 * the declared families finish loading, so layout never reuses widths that
 * were measured with fallback metrics. Clearing always happens before the
 * notification, which makes the re-layout order deterministic.
 */
export function watchBrandFontsLoaded({
  fontFaceSet,
  families,
  clearMeasurementCaches,
  onFontsSettled,
}: WatchBrandFontsOptions): () => void {
  if (families.length === 0 || !fontFaceSet) return () => undefined;
  let isCancelled = false;
  const settle = () => {
    if (isCancelled) return;
    clearMeasurementCaches();
    onFontsSettled();
  };
  fontFaceSet.addEventListener("loadingdone", settle);
  void Promise.all(families.map((family) => fontFaceSet.load(`16px ${JSON.stringify(family)}`)))
    .then(() => fontFaceSet.ready)
    .then(settle)
    .catch(() => undefined);
  return () => {
    isCancelled = true;
    fontFaceSet.removeEventListener("loadingdone", settle);
  };
}
