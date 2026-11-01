import { reviewIntent } from "../review/intent";
import { stopReview } from "../review/flow";

/** "That's enough for now", "pause", "later": stops, and says unanswered ones will still be waiting. */
export const reviewDoneIntent = reviewIntent({
  id: "review-done",
  name: "DoneReviewingIntent",
  samples: ["that's enough", "that's enough for now", "I'm done", "I'm done for now", "done", "pause", "take a break", "later", "let's stop here", "stop reviewing", "we're done", "finish", "that's all"],
  handle: (handlerInput) => stopReview(handlerInput),
});
