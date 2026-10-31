import { getIntentName, getRequestType } from "ask-sdk-core";
import type { IntentModule } from "../contracts";
import { readHeadlines } from "../speech/conversation";

export const INTENT_NAME = "AMAZON.FallbackIntent";

/** What the skill answers when it did not understand: the headlines, so there is always something to choose from. */
export const fallbackIntent: IntentModule = {
  id: "fallback",
  create: (dependencies) => ({
    canHandle: (handlerInput) => getRequestType(handlerInput.requestEnvelope) === "IntentRequest" && getIntentName(handlerInput.requestEnvelope) === INTENT_NAME,
    handle: (handlerInput) => readHeadlines(handlerInput, dependencies, { greeting: "Sorry, I did not catch that." }),
  }),
  interactionModel: { intent: { name: INTENT_NAME, samples: [] } },
};
