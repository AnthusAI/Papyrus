import { getIntentName, getRequestType } from "ask-sdk-core";
import type { IntentModule } from "../contracts";
import { inReview } from "../review/flow";
import { readHeadlines } from "../speech/conversation";
import { sentence, wrapSpeak } from "../speech/ssml";

export const INTENT_NAME = "AMAZON.FallbackIntent";

/** What the skill answers when it did not understand: the headlines, so there is always something to choose from. */
export const fallbackIntent: IntentModule = {
  id: "fallback",
  create: (dependencies) => ({
    canHandle: (handlerInput) => getRequestType(handlerInput.requestEnvelope) === "IntentRequest" && getIntentName(handlerInput.requestEnvelope) === INTENT_NAME,
    handle: (handlerInput) =>
      inReview(handlerInput)
        ? handlerInput.responseBuilder
            .speak(wrapSpeak(sentence("Sorry, I didn't catch that. Say accept, reject and why, or skip. Or say help.")))
            .reprompt(wrapSpeak(sentence("Accept, reject, or skip?")))
            .withShouldEndSession(false)
            .getResponse()
        : readHeadlines(handlerInput, dependencies, { greeting: "Sorry, I did not catch that." }),
  }),
  interactionModel: { intent: { name: INTENT_NAME, samples: [] } },
};
