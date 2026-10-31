import type { IntentModule } from "../contracts";

/**
 * A placeholder so the skeleton answers "Alexa, open ...". The intents task replaces this file's content: the real launch reads
 * the latest headlines from `dependencies.stories`.
 */
export const launchIntent: IntentModule = {
  id: "launch",
  create: () => ({
    canHandle: (handlerInput) => handlerInput.requestEnvelope.request.type === "LaunchRequest",
    handle: (handlerInput) =>
      handlerInput.responseBuilder.speak("This skill is still being set up. Please try again soon.").withShouldEndSession(true).getResponse(),
  }),
};
