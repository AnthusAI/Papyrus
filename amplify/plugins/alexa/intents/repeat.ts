import { getIntentName, getRequestType } from "ask-sdk-core";
import type { IntentModule } from "../contracts";
import { currentPosition, NOTHING_PUBLISHED, readHeadlines, readStory, sayAndEnd } from "../speech/conversation";

export const INTENT_NAME = "AMAZON.RepeatIntent";

/** "Repeat": the story being read, or the headline list when no story has been picked yet. */
export const repeatIntent: IntentModule = {
  id: "repeat",
  create: (dependencies) => ({
    canHandle: (handlerInput) => getRequestType(handlerInput.requestEnvelope) === "IntentRequest" && getIntentName(handlerInput.requestEnvelope) === INTENT_NAME,
    handle: async (handlerInput) => {
      const position = await currentPosition(handlerInput, dependencies);
      if (position === undefined) return sayAndEnd(handlerInput, NOTHING_PUBLISHED);
      if (position.current === null) return readHeadlines(handlerInput, dependencies, { position });
      return readStory(handlerInput, dependencies, position, position.current);
    },
  }),
  interactionModel: { intent: { name: INTENT_NAME, samples: ["say that again", "read it again", "read that again", "once more"] } },
};
