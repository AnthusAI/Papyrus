import type { IntentModule } from "../contracts";
import { linkedUser } from "../auth";
import { EDITOR_GROUPS } from "../review/flow";
import { readHeadlines } from "../speech/conversation";
import { sentence, wrapSpeak } from "../speech/ssml";

/**
 * "Alexa, open <publication>". A linked editor is offered review first (the newsroom's work), with the stories a word away; anyone
 * else hears the latest headlines.
 */
export const launchIntent: IntentModule = {
  id: "launch",
  create: (dependencies) => ({
    canHandle: (handlerInput) => handlerInput.requestEnvelope.request.type === "LaunchRequest",
    handle: async (handlerInput) => {
      const user = dependencies.review ? await linkedUser(handlerInput, dependencies.tokens) : null;
      if (user && user.groups.some((group) => EDITOR_GROUPS.includes(group))) {
        return handlerInput.responseBuilder
          .speak(
            wrapSpeak(
              [
                `Welcome to ${dependencies.config.skillName}.`,
                "Say needs my help to review the references I'm least sure about, best bets for the ones I think you'll like, or headlines for the latest stories.",
              ]
                .map(sentence)
                .join(""),
            ),
          )
          .reprompt(wrapSpeak(sentence("Say needs my help, best bets, or headlines.")))
          .withShouldEndSession(false)
          .getResponse();
      }
      return readHeadlines(handlerInput, dependencies, { greeting: `Welcome to ${dependencies.config.skillName}.`, fresh: true });
    },
  }),
};
