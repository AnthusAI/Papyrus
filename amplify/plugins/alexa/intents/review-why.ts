import { reviewIntent } from "../review/intent";
import { why } from "../review/flow";

/** "Why this one", "how sure are you": the Cyclotron's guess in plain words. */
export const reviewWhyIntent = reviewIntent({
  id: "review-why",
  name: "WhyThisReferenceIntent",
  samples: ["why", "why this one", "why is this here", "why did you pick this", "why do you think I'd like this", "why do you think I'd like it", "how sure are you", "what do you think", "what's your guess", "what would you do", "do you think I'd like it", "what does the cyclotron think"],
  handle: (handlerInput) => why(handlerInput),
});
