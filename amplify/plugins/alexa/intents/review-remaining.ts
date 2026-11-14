import { reviewIntent } from "../review/intent";
import { remaining } from "../review/flow";

/** "How many are left". */
export const reviewRemainingIntent = reviewIntent({
  id: "review-remaining",
  name: "HowManyLeftIntent",
  samples: ["how many are left", "how many left", "how many more", "how many more are there", "how many to go", "how many are there", "how many references are left", "how many references are waiting", "where am I", "how far along am I", "am I done"],
  handle: (handlerInput) => remaining(handlerInput),
});
