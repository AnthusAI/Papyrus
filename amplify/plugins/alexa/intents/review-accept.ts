import { reviewIntent } from "../review/intent";
import { vote } from "../review/flow";

/** "Accept", "keep it", "yes": accepts the Reference under review and reads the next. */
export const reviewAcceptIntent = reviewIntent({
  id: "review-accept",
  name: "AcceptReferenceIntent",
  samples: ["accept", "accept it", "accept this one", "accept that", "accepted", "approve", "approve it", "keep it", "keep this one", "keep", "yes", "yes accept", "yes keep it", "include it", "it's good", "that's a good one", "thumbs up", "sure accept it"],
  handle: (handlerInput, dependencies) => vote(handlerInput, dependencies, "accept"),
});
