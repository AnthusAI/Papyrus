import type { PublicStorySource } from "../contracts";

/** The placeholder source. It fails loudly instead of answering with an empty list, so a skill without a real source cannot look healthy. */
export const stubPublicStorySource: PublicStorySource = {
  async listLatest() {
    throw new Error("The alexa plugin has no public story source yet (amplify/plugins/alexa/content/index.ts).");
  },
  async getStory() {
    throw new Error("The alexa plugin has no public story source yet (amplify/plugins/alexa/content/index.ts).");
  },
};
