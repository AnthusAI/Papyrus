import { reviewIntent } from "../review/intent";
import { skip } from "../review/flow";

/** "Skip", "not sure", "come back to it": moves on without an answer. */
export const reviewSkipIntent = reviewIntent({
  id: "review-skip",
  name: "SkipReferenceIntent",
  samples: ["skip", "skip it", "skip this one", "skip that", "pass", "not sure", "I'm not sure", "I don't know", "dunno", "come back to it", "come back to this one", "maybe later", "leave it", "leave it for now", "next reference", "move on"],
  handle: (handlerInput, dependencies) => skip(handlerInput, dependencies),
});
