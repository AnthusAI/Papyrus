import { SITE_BRAND, type SiteBrand } from "./site-brand";
import { isMissingHeadStageIndexError, type StageIndexMode } from "./story-stage-query";

let headStageIndexMissing = false;

/**
 * Which index the board's stage columns read. The head stage index once the site says it is filled (SiteBrand.storyHeadStageIndex, set
 * after `papyrus stories head-index` reports nothing left to write), else the stage index with its superseded filter, as before.
 * A backend that turns out not to have the index (an older data deploy) drops back to the stage index for the rest of the session.
 */
export function storyStageIndexMode(brand: Pick<SiteBrand, "storyHeadStageIndex"> = SITE_BRAND): StageIndexMode {
  return brand.storyHeadStageIndex === true && !headStageIndexMissing ? "head" : "stage";
}

export function markHeadStageIndexMissing(): void {
  headStageIndexMissing = true;
}

/** Read with the board's index, and drop back to the stage index for good when this backend has no head stage index. */
export async function readWithStoryStageIndex<T>(read: (mode: StageIndexMode) => Promise<T>, brand: Pick<SiteBrand, "storyHeadStageIndex"> = SITE_BRAND): Promise<T> {
  const mode = storyStageIndexMode(brand);
  try {
    return await read(mode);
  } catch (reason: unknown) {
    if (mode !== "head" || !isMissingHeadStageIndexError(reason)) throw reason;
    markHeadStageIndexMissing();
    return read("stage");
  }
}

/** Tests only. */
export function resetHeadStageIndexMissing(): void {
  headStageIndexMissing = false;
}
