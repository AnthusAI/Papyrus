import { GetParameterCommand, ParameterNotFound, SSMClient } from "@aws-sdk/client-ssm";
import { skillIdParameterName, type AlexaConfig } from "./config";

/** Reads a plain String SSM parameter; `undefined` when it does not exist. Any other failure throws (the request then fails closed). */
export type ParameterReader = (name: string) => Promise<string | undefined>;

export type SkillIdResolver = (config: AlexaConfig) => Promise<string | undefined>;

/** How long a missing skill ID is remembered before SSM is asked again: a skill created by the deploy sync starts serving without a cold start. */
export const MISSING_SKILL_ID_RETRY_MS = 60_000;

export function ssmParameterReader(client: SSMClient = new SSMClient({})): ParameterReader {
  return async (name) => {
    try {
      return (await client.send(new GetParameterCommand({ Name: name }))).Parameter?.Value;
    } catch (error) {
      if (error instanceof ParameterNotFound || (error as { name?: string })?.name === "ParameterNotFound") return undefined;
      throw error;
    }
  };
}

/**
 * The skill ID the endpoint accepts. `config.skillId` (an explicit override in the site config) wins; otherwise the deploy sync's
 * SSM parameter `/papyrus/<site-id>/alexa/skill-id`, read at cold start and cached for the life of the container. A missing
 * parameter is not cached for long and resolves to `undefined`, which the endpoint treats as "serve nothing" (fails closed).
 */
export function createSkillIdResolver(read: ParameterReader, now: () => number = Date.now): SkillIdResolver {
  let found: string | undefined;
  let missingSince: number | undefined;
  return async (config) => {
    if (config.skillId !== undefined) return config.skillId;
    if (found !== undefined) return found;
    if (missingSince !== undefined && now() - missingSince < MISSING_SKILL_ID_RETRY_MS) return undefined;
    const value = (await read(skillIdParameterName(config)))?.trim();
    if (value === undefined || value === "") {
      missingSince = now();
      return undefined;
    }
    found = value;
    return found;
  };
}
