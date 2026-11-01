import { getIntentName, getRequestType } from "ask-sdk-core";
import type { IntentModule } from "../contracts";
import { inReview, reviewHelp } from "../review/flow";
import { say } from "../speech/conversation";
import { sentence, wrapSpeak } from "../speech/ssml";

export const INTENT_NAME = "AMAZON.HelpIntent";

export const helpIntent: IntentModule = {
  id: "help",
  create: (dependencies) => ({
    canHandle: (handlerInput) => getRequestType(handlerInput.requestEnvelope) === "IntentRequest" && getIntentName(handlerInput.requestEnvelope) === INTENT_NAME,
    handle: (handlerInput) =>
      inReview(handlerInput) ? reviewHelp(handlerInput) : say(
        handlerInput,
        wrapSpeak(
          [
            `${dependencies.config.skillName} reads you its latest published stories.`,
            "Say a number to hear a story, like the second one.",
            "Say next or previous to move between stories, repeat to hear one again, or headlines for the list.",
            "Editors can also say needs my help, or best bets, to review references.",
            "Say stop to leave. What would you like?",
          ]
            .map(sentence)
            .join(""),
        ),
        wrapSpeak(sentence("Say a number, next, headlines, or stop.")),
      ),
  }),
  interactionModel: { intent: { name: INTENT_NAME, samples: [] } },
};
