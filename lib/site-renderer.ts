import { MarkusSiteRendererError, assertPretextRendererConfig } from "./renderer-config";
import { SITE_BRAND } from "./site-brand";
import type { Renderer } from "./renderer";
import { pretextRenderer } from "../renderers/pretext";

export { MarkusSiteRendererError } from "./renderer-config";

export function assertPretextSite(): void {
  const config = SITE_BRAND.rendererConfig;
  if (config.kind === "markus") {
    throw new MarkusSiteRendererError(config.theme, SITE_BRAND.id);
  }
  assertPretextRendererConfig(config);
}

export function getSiteRenderer(): Renderer {
  assertPretextSite();
  return pretextRenderer;
}
