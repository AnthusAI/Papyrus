import type { EditionPresentationFormat } from "../../lib/content-types";
import type { Renderer } from "../../lib/renderer";
import { MarkusArticleStub, MarkusEditionStub, MarkusItemStub } from "./stubs";

/** CSS paths relative to the static site root (`web/dist/`). */
export const MARKUS_STYLESHEETS = ["css/markus-vendor.css", "css/site-theme.css"] as const;

export function markusSupportsLayout(_layout: EditionPresentationFormat): boolean {
  return false;
}

/**
 * Markus renderer: Python build emits static HTML under `web/dist/`.
 * Preview with `python -m http.server` on that folder — no Next.js shell.
 */
export const markusRenderer: Renderer = {
  id: "markus",
  renderEdition: MarkusEditionStub,
  renderArticle: MarkusArticleStub,
  renderItem: MarkusItemStub,
  stylesheets: () => [...MARKUS_STYLESHEETS],
  supportsLayout: markusSupportsLayout,
};

export { MarkusArticleStub, MarkusEditionStub, MarkusItemStub } from "./stubs";
