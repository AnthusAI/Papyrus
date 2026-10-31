import { getIntentName, getRequestType } from "ask-sdk-core";
import type { IntentModule } from "../contracts";
import { currentPosition, NOTHING_PUBLISHED, readStory, say, sayAndEnd } from "../speech/conversation";
import { sentence, wrapSpeak } from "../speech/ssml";

export const INTENT_NAME = "AMAZON.NextIntent";

/** "Next": the next story, or the first one when the listener is still at the headlines. */
export const nextIntent: IntentModule = {
  id: "next",
  create: (dependencies) => ({
    canHandle: (handlerInput) => getRequestType(handlerInput.requestEnvelope) === "IntentRequest" && getIntentName(handlerInput.requestEnvelope) === INTENT_NAME,
    handle: async (handlerInput) => {
      const position = await currentPosition(handlerInput, dependencies);
      if (position === undefined) return sayAndEnd(handlerInput, NOTHING_PUBLISHED);
      const target = position.current === null ? 0 : position.current + 1;
      if (target >= position.headlines.length) {
        return say(
          handlerInput,
          wrapSpeak(sentence("That was the last of the latest stories. Say previous to go back, headlines for the list again, or stop.")),
          wrapSpeak(sentence("Say previous, headlines, or stop.")),
        );
      }
      return readStory(handlerInput, dependencies, position, target);
    },
  }),
  interactionModel: { intent: { name: INTENT_NAME, samples: ["next story", "read the next one", "skip this one", "go on to the next story"] } },
};
