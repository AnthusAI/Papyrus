import { getIntentName, getRequestType } from "ask-sdk-core";
import type { IntentModule } from "../contracts";
import { readHeadlines } from "../speech/conversation";

export const INTENT_NAME = "AMAZON.NavigateHomeIntent";

/** "Go home": back to the headlines, fresh from the site. */
export const navigateHomeIntent: IntentModule = {
  id: "navigate-home",
  create: (dependencies) => ({
    canHandle: (handlerInput) => getRequestType(handlerInput.requestEnvelope) === "IntentRequest" && getIntentName(handlerInput.requestEnvelope) === INTENT_NAME,
    handle: (handlerInput) => readHeadlines(handlerInput, dependencies, { fresh: true }),
  }),
  interactionModel: { intent: { name: INTENT_NAME, samples: [] } },
};
