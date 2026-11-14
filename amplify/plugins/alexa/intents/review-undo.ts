import { reviewIntent } from "../review/intent";
import { undo } from "../review/flow";

/** "Undo", "I changed my mind": takes back the last answer and reads that Reference again. */
export const reviewUndoIntent = reviewIntent({
  id: "review-undo",
  name: "UndoVoteIntent",
  samples: ["undo", "undo that", "undo it", "take that back", "take it back", "I changed my mind", "change my answer", "change that", "that was wrong", "oops", "wait no", "I didn't mean that", "go back and change it"],
  handle: (handlerInput, dependencies) => undo(handlerInput, dependencies),
});
