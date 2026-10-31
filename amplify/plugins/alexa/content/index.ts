import type { AlexaConfig } from "../config";
import type { PublicStorySource } from "../contracts";
import { stubPublicStorySource } from "./stub-public-story-source";

/**
 * The seam for the public story source. A real source is a file in this folder; switch to it by changing the return line.
 */
export function createPublicStorySource(_config: AlexaConfig): PublicStorySource {
  return stubPublicStorySource;
}
