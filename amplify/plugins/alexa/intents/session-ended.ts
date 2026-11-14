import { getRequestType } from "ask-sdk-core";
import type { IntentModule } from "../contracts";

/** The session ended (the listener left, a timeout, or an error): Alexa takes no speech, so the answer is empty. */
export const sessionEndedIntent: IntentModule = {
  id: "session-ended",
  create: () => ({
    canHandle: (handlerInput) => getRequestType(handlerInput.requestEnvelope) === "SessionEndedRequest",
    handle: (handlerInput) => {
      const request = handlerInput.requestEnvelope.request;
      if (request.type === "SessionEndedRequest" && request.error !== undefined) console.error("alexa session ended with an error", request.error);
      return handlerInput.responseBuilder.getResponse();
    },
  }),
};
