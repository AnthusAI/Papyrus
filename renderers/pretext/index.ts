import type { Renderer } from "../../lib/renderer";
import { PRETEXT_LAYOUTS, pretextSupportsLayout } from "./layouts";
import { ArticlePageView, ItemPageView } from "./article-page";
import { PresentationShell } from "./presentation-shell";

export { ArticlePageView, ItemPageView } from "./article-page";
export { PresentationShell } from "./presentation-shell";
export type { PresentationTarget } from "./presentation-shell";
export { PRETEXT_LAYOUTS, pretextSupportsLayout } from "./layouts";

/**
 * The Pretext renderer: the existing client-side layout solver
 * (`@chenglou/pretext` + `components/newspaper.tsx` +
 * `renderers/pretext/presentation-shell.tsx`), retrofitted onto the
 * `Renderer` interface (lib/renderer.ts). This is a pure retrofit -- no
 * rendering behavior changed, only how the existing implementation is
 * exposed.
 */
export const pretextRenderer: Renderer = {
  id: "pretext",
  renderEdition: PresentationShell,
  renderArticle: ArticlePageView,
  renderItem: ItemPageView,
  // Pretext's CSS is not extracted from the monolithic app/globals.css
  // bundle imported unconditionally by app/layout.tsx, so there is nothing
  // additional for this renderer to declare today. See lib/renderer.ts's
  // `stylesheets` doc comment.
  stylesheets: () => [],
  supportsLayout: pretextSupportsLayout,
};
