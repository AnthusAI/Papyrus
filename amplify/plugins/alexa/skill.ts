import { SkillBuilders, type Skill } from "ask-sdk-core";
import type { RequestEnvelope, ResponseEnvelope } from "ask-sdk-model";
import { createAccessTokenVerifier } from "./auth";
import type { AlexaConfig } from "./config";
import { createPublicStorySource } from "./content";
import type { IntentModule, SkillDependencies } from "./contracts";
import { INTENT_MODULES } from "./intents";

export class SkillIdMismatchError extends Error {}

/** The skill ID a request claims, from the session or (for requests without one) the system context. */
export function requestSkillId(event: RequestEnvelope): string | undefined {
  return event.session?.application?.applicationId ?? event.context?.System?.application?.applicationId;
}

export function defaultDependencies(config: AlexaConfig): SkillDependencies {
  return { config, stories: createPublicStorySource(config), tokens: createAccessTokenVerifier(config) };
}

export function buildSkill(dependencies: SkillDependencies, modules: readonly IntentModule[] = INTENT_MODULES): Skill {
  return SkillBuilders.custom()
    .addRequestHandlers(...modules.map((module) => module.create(dependencies)))
    .addErrorHandlers({
      canHandle: () => true,
      handle: (handlerInput, error) => {
        console.error("alexa skill error", error);
        return handlerInput.responseBuilder.speak("Sorry, something went wrong. Please try again.").withShouldEndSession(true).getResponse();
      },
    })
    .create();
}

/**
 * The endpoint's request validation. The skill ID check fails closed: until the site's config names a skill ID, no request is
 * served. (The Lambda permission's event-source condition is the first gate; this is the second.)
 */
export async function invokeSkill(
  event: RequestEnvelope,
  config: AlexaConfig,
  dependencies: SkillDependencies = defaultDependencies(config),
  modules: readonly IntentModule[] = INTENT_MODULES,
): Promise<ResponseEnvelope> {
  if (config.skillId === undefined) throw new SkillIdMismatchError("The alexa plugin has no skillId configured, so it serves no request.");
  if (requestSkillId(event) !== config.skillId) throw new SkillIdMismatchError("Request skill ID does not match the configured skill.");
  return buildSkill(dependencies, modules).invoke(event);
}
