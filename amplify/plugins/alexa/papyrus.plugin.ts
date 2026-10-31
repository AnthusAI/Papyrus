import { ServicePrincipal } from "aws-cdk-lib/aws-iam";
import type { Function as LambdaFunction } from "aws-cdk-lib/aws-lambda";
import type { PapyrusPlugin, PluginManifest, PluginWiringContext } from "../types";
import { ALEXA_SETTINGS_ENVIRONMENT_VARIABLE, resolveAlexaConfig, type AlexaConfig } from "./config";
import { ALEXA_STATIC_ASSETS } from "./static-assets";
import { alexaSkill } from "./function/resource";
import { ALEXA_WIRING_STEPS } from "./wiring";

export { resolveAlexaConfig };
export type { AlexaConfig };

/** `custom.alexa.functionArn` in `amplify_outputs.json`: the endpoint the skill manifest points at. */
export const ALEXA_OUTPUT_KEY = "alexa";
export const ALEXA_APPKIT_PRINCIPAL = "alexa-appkit.amazon.com";

export const alexaManifest: PluginManifest = {
  name: "alexa",
  contract: 1,
  models: [],
  mutations: [],
  guest: { mutations: [] },
  newsroomPanels: [],
  staticAssets: [...ALEXA_STATIC_ASSETS],
};

export const alexaPlugin: PapyrusPlugin<AlexaConfig, { alexaSkill: typeof alexaSkill }> = {
  manifest: alexaManifest,
  resolveConfig: resolveAlexaConfig,
  functions: () => ({ alexaSkill }),
  schemaDefinitions: () => ({}),
  publicSettings: (config) => ({
    contract: alexaManifest.contract,
    invocationName: config.invocationName,
    accountLinking: config.accountLinking,
  }),
  wire(backend, config, context: PluginWiringContext) {
    const lambda = backend.alexaSkill.resources.lambda as LambdaFunction;
    // Only the Alexa service may invoke the function, and only for this skill once its ID is known. Until then the handler refuses
    // every request, so the function is never open to someone else's skill.
    lambda.addPermission("AlexaSkillInvoke", {
      principal: new ServicePrincipal(ALEXA_APPKIT_PRINCIPAL),
      action: "lambda:InvokeFunction",
      ...(config.skillId === undefined ? {} : { eventSourceToken: config.skillId }),
    });
    lambda.addEnvironment(ALEXA_SETTINGS_ENVIRONMENT_VARIABLE, JSON.stringify(config));
    backend.addOutput({ custom: { [ALEXA_OUTPUT_KEY]: { functionArn: lambda.functionArn } } });
    for (const step of ALEXA_WIRING_STEPS) step(backend, config, context, lambda);
  },
};
