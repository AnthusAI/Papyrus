import type { IntentModule } from "../contracts";
import { readHeadlines } from "../speech/conversation";

/** "Alexa, open <publication>": reads the latest headlines and asks which story. */
export const launchIntent: IntentModule = {
  id: "launch",
  create: (dependencies) => ({
    canHandle: (handlerInput) => handlerInput.requestEnvelope.request.type === "LaunchRequest",
    handle: (handlerInput) =>
      readHeadlines(handlerInput, dependencies, { greeting: `Welcome to ${dependencies.config.skillName}.`, fresh: true }),
  }),
};
