import { getIntentName, getRequestType } from "ask-sdk-core";
import type { IntentModule } from "../contracts";
import { say } from "../speech/conversation";
import { sentence, wrapSpeak } from "../speech/ssml";

export const INTENT_NAME = "AMAZON.FallbackIntent";

/** What the skill answers when it did not understand: the ways to move, and the session stays open. */
export const fallbackIntent: IntentModule = {
  id: "fallback",
  create: () => ({
    canHandle: (handlerInput) => getRequestType(handlerInput.requestEnvelope) === "IntentRequest" && getIntentName(handlerInput.requestEnvelope) === INTENT_NAME,
    handle: (handlerInput) =>
      say(
        handlerInput,
        wrapSpeak(sentence("Sorry, I did not get that. Say the number of a story, next, headlines, or help.")),
        wrapSpeak(sentence("Say the number of a story, or say help.")),
      ),
  }),
  interactionModel: { intent: { name: INTENT_NAME, samples: [] } },
};
