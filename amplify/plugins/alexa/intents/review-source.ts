import { reviewIntent } from "../review/intent";
import { source } from "../review/flow";

/** "Who published it", "when was it published". */
export const reviewSourceIntent = reviewIntent({
  id: "review-source",
  name: "ReferenceSourceIntent",
  samples: ["who published it", "who published this", "who wrote it", "who wrote this", "where is it from", "where's it from", "where's this from", "what's the source", "what is the source", "when was it published", "when was this published", "how old is it", "how old is this", "what site is it from"],
  handle: (handlerInput, dependencies) => source(handlerInput, dependencies),
});
