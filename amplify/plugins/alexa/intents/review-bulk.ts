import { reviewIntent } from "../review/intent";
import { bulkRefused } from "../review/flow";

/** "Accept all": refused kindly; answers are one at a time. */
export const reviewBulkIntent = reviewIntent({
  id: "review-bulk",
  name: "BulkReviewIntent",
  samples: ["accept all", "accept all of them", "accept them all", "accept everything", "approve all", "approve them all", "reject all", "reject all of them", "reject them all", "reject everything", "skip all", "skip them all"],
  handle: (handlerInput) => bulkRefused(handlerInput),
});
