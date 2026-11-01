import { getIntentName, getRequestType, type HandlerInput } from "ask-sdk-core";
import type { Response } from "ask-sdk-model";
import type { InteractionModelSlot, InteractionModelType, IntentModule, SkillDependencies } from "../contracts";

/** One review intent: a custom intent name, its samples, and what it does. Keeps each `intents/review-*.ts` file to its words. */
export function reviewIntent(options: {
  id: string;
  name: string;
  samples: string[];
  slots?: InteractionModelSlot[];
  types?: InteractionModelType[];
  handle: (handlerInput: HandlerInput, dependencies: SkillDependencies) => Response | Promise<Response>;
}): IntentModule {
  return {
    id: options.id,
    create: (dependencies) => ({
      canHandle: (handlerInput) => getRequestType(handlerInput.requestEnvelope) === "IntentRequest" && getIntentName(handlerInput.requestEnvelope) === options.name,
      handle: (handlerInput) => options.handle(handlerInput, dependencies),
    }),
    interactionModel: {
      intent: { name: options.name, samples: options.samples, ...(options.slots ? { slots: options.slots } : {}) },
      ...(options.types ? { types: options.types } : {}),
    },
  };
}
