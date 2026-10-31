import { getIntentName, getRequestType, getSlotValue } from "ask-sdk-core";
import type { IntentModule } from "../contracts";
import { currentPosition, NOTHING_PUBLISHED, readStory, sayAndEnd, say, storyNumber } from "../speech/conversation";
import { sentence, wrapSpeak } from "../speech/ssml";

export const INTENT_NAME = "ReadStoryIntent";

/** "Read the second one", "story 3": reads that story's deck and the first part of its body. */
export const readStoryIntent: IntentModule = {
  id: "read-story",
  create: (dependencies) => ({
    canHandle: (handlerInput) => getRequestType(handlerInput.requestEnvelope) === "IntentRequest" && getIntentName(handlerInput.requestEnvelope) === INTENT_NAME,
    handle: async (handlerInput) => {
      const position = await currentPosition(handlerInput, dependencies);
      if (position === undefined) return sayAndEnd(handlerInput, NOTHING_PUBLISHED);

      const number = storyNumber(getSlotValue(handlerInput.requestEnvelope, "ordinal"), getSlotValue(handlerInput.requestEnvelope, "number"));
      const count = position.headlines.length;
      if (number === undefined) {
        return say(handlerInput, wrapSpeak(sentence("Which story would you like? Say the number, like the second one.")), wrapSpeak(sentence("Say the number of a story.")));
      }
      if (number < 1 || number > count) {
        const range = count === 1 ? "I only have one story" : `I only have ${count} stories`;
        return say(handlerInput, wrapSpeak(sentence(`${range}. Say a number from one to ${count}.`)), wrapSpeak(sentence("Say the number of a story.")));
      }
      return readStory(handlerInput, dependencies, position, number - 1);
    },
  }),
  interactionModel: {
    intent: {
      name: INTENT_NAME,
      slots: [
        { name: "ordinal", type: "AMAZON.Ordinal" },
        { name: "number", type: "AMAZON.NUMBER" },
      ],
      samples: [
        "read the {ordinal} one",
        "read the {ordinal} story",
        "read me the {ordinal} one",
        "read me the {ordinal} story",
        "tell me the {ordinal} one",
        "play the {ordinal} one",
        "open the {ordinal} one",
        "I want the {ordinal} one",
        "the {ordinal} one",
        "the {ordinal} story",
        "{ordinal}",
        "story {number}",
        "read story {number}",
        "story number {number}",
        "read story number {number}",
        "number {number}",
        "read number {number}",
        "{number}",
      ],
    },
  },
};
