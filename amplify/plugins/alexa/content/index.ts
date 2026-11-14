import type { AlexaConfig } from "../config";
import type { PublicStorySource } from "../contracts";
import { createPublicSiteStorySource } from "./public-site-story-source";
import { stubPublicStorySource } from "./stub-public-story-source";

/**
 * The seam for the public story source. The real one reads the site's public projection, so it needs the site's origin; without
 * `siteOrigin` the stub is returned and fails loudly the first time it is asked for stories.
 */
export function createPublicStorySource(config: AlexaConfig): PublicStorySource {
  return config.siteOrigin === undefined ? stubPublicStorySource : createPublicSiteStorySource({ origin: config.siteOrigin });
}
