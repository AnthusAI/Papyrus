import { getIntentName, getRequestType } from "ask-sdk-core";
import type { IntentModule } from "../contracts";
import { currentPosition, NOTHING_PUBLISHED, readHeadlines, readStory, sayAndEnd } from "../speech/conversation";

export const INTENT_NAME = "ContinueIntent";

/** "Continue", "keep reading": the next part of the story being read; at the headlines, the first story. */
export const continueIntent: IntentModule = {
  id: "continue",
  create: (dependencies) => ({
    canHandle: (handlerInput) => getRequestType(handlerInput.requestEnvelope) === "IntentRequest" && getIntentName(handlerInput.requestEnvelope) === INTENT_NAME,
    handle: async (handlerInput) => {
      const position = await currentPosition(handlerInput, dependencies);
      if (position === undefined) return sayAndEnd(handlerInput, NOTHING_PUBLISHED);
      if (position.current === null) return readHeadlines(handlerInput, dependencies, { position });
      return readStory(handlerInput, dependencies, position, position.current, (position.part ?? 0) + 1);
    },
  }),
  interactionModel: {
    intent: {
      name: INTENT_NAME,
      samples: ["continue", "keep reading", "keep going", "go on", "more", "read more", "tell me more", "continue reading", "carry on", "and then", "what else"],
    },
  },
};
