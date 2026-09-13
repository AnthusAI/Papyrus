import { MarkusSiteRendererError } from "./renderer-config";
import { SITE_BRAND } from "./site-brand";
import type { Renderer } from "./renderer";
import { pretextRenderer } from "../renderers/pretext";

export { MarkusSiteRendererError } from "./renderer-config";

export function assertPretextSite(): void {
  if (SITE_BRAND.renderer.kind === "markus") {
    throw new MarkusSiteRendererError("hackerman", SITE_BRAND.id);
  }
}

export function getSiteRenderer(): Renderer {
  assertPretextSite();
  return pretextRenderer;
}
