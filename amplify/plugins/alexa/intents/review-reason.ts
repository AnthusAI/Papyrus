import { getSlotValue } from "ask-sdk-core";
import { reviewIntent } from "../review/intent";
import { reviewState, vote } from "../review/flow";
import { sentence, wrapSpeak } from "../speech/ssml";

/** "Because it's off topic": the reason after a bare "reject" (the skill asked why). Said out of the blue, it checks first. */
export const reviewReasonIntent = reviewIntent({
  id: "review-reason",
  name: "RejectReasonIntent",
  samples: ["because {reason}", "it's {reason}", "it is {reason}", "the reason is {reason}", "reason {reason}", "since {reason}"],
  slots: [{ name: "reason", type: "AMAZON.SearchQuery" }],
  handle: (handlerInput, dependencies) => {
    const reason = getSlotValue(handlerInput.requestEnvelope, "reason") ?? undefined;
    if (reviewState(handlerInput)?.awaitingReason) return vote(handlerInput, dependencies, "reject", reason);
    return handlerInput.responseBuilder
      .speak(wrapSpeak(sentence("Did you want to reject it? Say reject, then because and the reason. Or say accept, or skip.")))
      .reprompt(wrapSpeak(sentence("Accept, reject, or skip?")))
      .withShouldEndSession(false)
      .getResponse();
  },
});
