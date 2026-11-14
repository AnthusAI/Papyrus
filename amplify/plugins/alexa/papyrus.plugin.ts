import { Stack } from "aws-cdk-lib";
import { PolicyStatement, ServicePrincipal } from "aws-cdk-lib/aws-iam";
import type { Function as LambdaFunction } from "aws-cdk-lib/aws-lambda";
import type { PapyrusPlugin, PluginManifest, PluginWiringContext } from "../types";
import { ALEXA_SETTINGS_ENVIRONMENT_VARIABLE, resolveAlexaConfig, skillIdParameterName, type AlexaConfig } from "./config";
import { ALEXA_APPKIT_PRINCIPAL_NAME } from "./principal";
import { ALEXA_STATIC_ASSETS } from "./static-assets";
import { alexaSkill } from "./function/resource";
import { ALEXA_WIRING_STEPS } from "./wiring";

export { resolveAlexaConfig };
export type { AlexaConfig };

/**
 * `custom.alexa.functionArn` in `amplify_outputs.json`: the endpoint the skill manifest points at. `custom.alexa.settings` is the
 * resolved config (nothing in it is secret), so the deploy sync needs no copy of the site's papyrus.config.ts.
 */
export const ALEXA_OUTPUT_KEY = "alexa";
export const ALEXA_APPKIT_PRINCIPAL = ALEXA_APPKIT_PRINCIPAL_NAME;

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
    // Only the Alexa service may invoke the function. Amazon accepts a Lambda endpoint only once the trigger exists, so the first
    // deploy creates it without an event-source condition (or with `config.skillId`, when the site config names one). The deploy sync
    // (docs/alexa.md, "Deploying the skill") replaces it with a skill-ID-scoped permission as soon as it has created the skill, and
    // re-checks on every deploy. In between, the handler is the gate: it serves nothing until the skill ID exists in SSM.
    lambda.addPermission("AlexaSkillInvoke", {
      principal: new ServicePrincipal(ALEXA_APPKIT_PRINCIPAL),
      action: "lambda:InvokeFunction",
      ...(config.skillId === undefined ? {} : { eventSourceToken: config.skillId }),
    });
    // The handler reads the skill ID the deploy sync stored (a plain String parameter) at cold start.
    lambda.addToRolePolicy(
      new PolicyStatement({
        actions: ["ssm:GetParameter"],
        resources: [Stack.of(lambda).formatArn({ service: "ssm", resource: "parameter", resourceName: skillIdParameterName(config).slice(1) })],
      }),
    );
    lambda.addEnvironment(ALEXA_SETTINGS_ENVIRONMENT_VARIABLE, JSON.stringify(config));
    backend.addOutput({ custom: { [ALEXA_OUTPUT_KEY]: { functionArn: lambda.functionArn, settings: config } } });
    for (const step of ALEXA_WIRING_STEPS) step(backend, config, context, lambda);
  },
};
