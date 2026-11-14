import { getIntentName, getRequestType } from "ask-sdk-core";
import type { IntentModule } from "../contracts";
import { inReview, stopReview } from "../review/flow";
import { sayAndEnd } from "../speech/conversation";
import { sentence, wrapSpeak } from "../speech/ssml";

export const INTENT_NAME = "AMAZON.StopIntent";

/** "Stop": say goodbye and end the session. */
export const stopIntent: IntentModule = {
  id: "stop",
  create: () => ({
    canHandle: (handlerInput) => getRequestType(handlerInput.requestEnvelope) === "IntentRequest" && getIntentName(handlerInput.requestEnvelope) === INTENT_NAME,
    handle: (handlerInput) => (inReview(handlerInput) ? stopReview(handlerInput) : sayAndEnd(handlerInput, wrapSpeak(sentence("Goodbye.")))),
  }),
  interactionModel: { intent: { name: INTENT_NAME, samples: [] } },
};
