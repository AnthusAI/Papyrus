import { getIntentName, getRequestType } from "ask-sdk-core";
import type { IntentModule } from "../contracts";
import { inReview, previous } from "../review/flow";
import { currentPosition, NOTHING_PUBLISHED, readStory, say, sayAndEnd } from "../speech/conversation";
import { sentence, wrapSpeak } from "../speech/ssml";

export const INTENT_NAME = "AMAZON.PreviousIntent";

/** "Previous": the story before the current one. */
export const previousIntent: IntentModule = {
  id: "previous",
  create: (dependencies) => ({
    canHandle: (handlerInput) => getRequestType(handlerInput.requestEnvelope) === "IntentRequest" && getIntentName(handlerInput.requestEnvelope) === INTENT_NAME,
    handle: async (handlerInput) => {
      if (inReview(handlerInput)) return previous(handlerInput, dependencies);
      const position = await currentPosition(handlerInput, dependencies);
      if (position === undefined) return sayAndEnd(handlerInput, NOTHING_PUBLISHED);
      if (position.current === null || position.current === 0) {
        return say(
          handlerInput,
          wrapSpeak(sentence("There is no story before this one. Say next, repeat, or headlines.")),
          wrapSpeak(sentence("Say next, repeat, or headlines.")),
        );
      }
      return readStory(handlerInput, dependencies, position, position.current - 1);
    },
  }),
  interactionModel: { intent: { name: INTENT_NAME, samples: ["previous story", "go back to the last one", "read the one before"] } },
};
