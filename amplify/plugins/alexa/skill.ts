import { SkillBuilders, type Skill } from "ask-sdk-core";
import type { RequestEnvelope, ResponseEnvelope } from "ask-sdk-model";
import { createAccessTokenVerifier } from "./auth";
import type { AlexaConfig } from "./config";
import { createPublicStorySource } from "./content";
import type { IntentModule, SkillDependencies } from "./contracts";
import { INTENT_MODULES } from "./intents";
import { createSkillIdResolver, ssmParameterReader, type SkillIdResolver } from "./skill-identity";

export class SkillIdMismatchError extends Error {}

/** The skill ID a request claims, from the session or (for requests without one) the system context. */
export function requestSkillId(event: RequestEnvelope): string | undefined {
  return event.session?.application?.applicationId ?? event.context?.System?.application?.applicationId;
}

let defaultSkillIdResolver: SkillIdResolver | undefined;

/** The container-wide resolver: the SSM client and the cached skill ID live as long as the Lambda container. */
function resolveSkillId(config: AlexaConfig): Promise<string | undefined> {
  defaultSkillIdResolver ??= createSkillIdResolver(ssmParameterReader());
  return defaultSkillIdResolver(config);
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
 * The endpoint's request validation. The skill ID check fails closed: until a skill ID is known (the deploy sync's SSM parameter,
 * or `skillId` in the site config), no request is served. (The Lambda permission's event-source condition is the first gate; this is the second.)
 */
export async function invokeSkill(
  event: RequestEnvelope,
  config: AlexaConfig,
  dependencies: SkillDependencies = defaultDependencies(config),
  modules: readonly IntentModule[] = INTENT_MODULES,
  skillIdResolver: SkillIdResolver = resolveSkillId,
): Promise<ResponseEnvelope> {
  const skillId = await skillIdResolver(config);
  if (skillId === undefined) throw new SkillIdMismatchError("The alexa plugin has no skill ID yet, so it serves no request.");
  if (requestSkillId(event) !== skillId) throw new SkillIdMismatchError("Request skill ID does not match the configured skill.");
  return buildSkill(dependencies, modules).invoke(event);
}
