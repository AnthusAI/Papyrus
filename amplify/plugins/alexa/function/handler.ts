import type { RequestEnvelope } from "ask-sdk-model";
import { ALEXA_SETTINGS_ENVIRONMENT_VARIABLE, type AlexaConfig } from "../config";
import { invokeSkill } from "../skill";

function settingsFromEnvironment(): AlexaConfig {
  const raw = process.env[ALEXA_SETTINGS_ENVIRONMENT_VARIABLE];
  if (raw === undefined) throw new Error(`${ALEXA_SETTINGS_ENVIRONMENT_VARIABLE} is not set`);
  return JSON.parse(raw) as AlexaConfig;
}

export const handler = async (event: RequestEnvelope) => invokeSkill(event, settingsFromEnvironment());
