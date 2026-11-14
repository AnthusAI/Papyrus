import { getSlotValue } from "ask-sdk-core";
import { reviewIntent } from "../review/intent";
import { vote } from "../review/flow";

/** "Reject because it's a press release": rejects with the reason in the editor's words. A bare "reject" asks why. */
export const reviewRejectIntent = reviewIntent({
  id: "review-reject",
  name: "RejectReferenceIntent",
  samples: [
    "reject",
    "reject it",
    "reject this one",
    "reject that",
    "no",
    "no thanks",
    "drop it",
    "toss it",
    "thumbs down",
    "reject because {reason}",
    "reject it because {reason}",
    "reject this because {reason}",
    "reject it it's {reason}",
    "reject it's {reason}",
    "reject {reason}",
    "no because {reason}",
    "no it's {reason}",
    "drop it because {reason}",
    "drop it it's {reason}",
  ],
  slots: [{ name: "reason", type: "AMAZON.SearchQuery" }],
  handle: (handlerInput, dependencies) => vote(handlerInput, dependencies, "reject", getSlotValue(handlerInput.requestEnvelope, "reason") ?? undefined),
});
