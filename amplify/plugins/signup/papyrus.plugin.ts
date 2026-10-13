import { Stack } from "aws-cdk-lib";
import { Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";
import type { Function as LambdaFunction } from "aws-cdk-lib/aws-lambda";
import type { PapyrusPlugin, PluginManifest, PluginRequest, PluginWiringContext } from "../types";
import { signupSubmit } from "./function/resource";
import { signupSchemaDefinitions } from "./schema";
import { SIGNUP_MUTATION_FIELD, WAF_MINIMUM_RATE_LIMIT, addSignupRateLimit } from "./waf";

export type SignupPluginConfig = {
  /** Form names the site accepts. A submission naming any other form is rejected. */
  forms: string[];
  /** Most submissions one address may make in a minute: enforced by the function and, with `waf`, by the web ACL. */
  addressLimitPerMinute: number;
  /** A regional web ACL with a rate-based rule on the API (about 6 USD a month). Off: the function's counters only. */
  waf: boolean;
};

const FORM_NAME = /^[a-z0-9][a-z0-9-]{0,39}$/;
const KNOWN_KEYS = new Set(["name", "forms", "addressLimitPerMinute", "waf"]);

export const signupManifest: PluginManifest = {
  name: "signup",
  contract: 1,
  models: ["SignupEntry"],
  mutations: [SIGNUP_MUTATION_FIELD],
  guest: { mutations: [SIGNUP_MUTATION_FIELD] },
  newsroomPanels: [{ id: "signups", label: "Signups" }],
  staticAssets: ["_plugins/papyrus-signup@1.js"],
};

export function resolveSignupConfig(request: PluginRequest): SignupPluginConfig {
  const raw = typeof request === "string" ? { name: request } : request;
  const unknown = Object.keys(raw).filter((key) => !KNOWN_KEYS.has(key));
  if (unknown.length > 0) throw new Error(`Unknown signup plugin settings: ${unknown.join(", ")}`);
  const forms = (raw.forms as string[] | undefined) ?? ["newsletter"];
  if (!Array.isArray(forms) || forms.length === 0 || !forms.every((form) => typeof form === "string" && FORM_NAME.test(form))) {
    throw new Error("signup plugin forms must be a non-empty list of lowercase names (letters, digits, hyphens; at most 40 characters)");
  }
  const addressLimitPerMinute = (raw.addressLimitPerMinute as number | undefined) ?? 20;
  if (!Number.isInteger(addressLimitPerMinute) || addressLimitPerMinute < WAF_MINIMUM_RATE_LIMIT || addressLimitPerMinute > 1000) {
    throw new Error(`signup plugin addressLimitPerMinute must be an integer from ${WAF_MINIMUM_RATE_LIMIT} to 1000`);
  }
  const waf = (raw.waf as boolean | undefined) ?? true;
  if (typeof waf !== "boolean") throw new Error("signup plugin waf must be a boolean");
  return { forms: [...new Set(forms)], addressLimitPerMinute, waf };
}

export const signupPlugin: PapyrusPlugin<SignupPluginConfig, { signupSubmit: typeof signupSubmit }> = {
  manifest: signupManifest,
  resolveConfig: resolveSignupConfig,
  functions: () => ({ signupSubmit }),
  schemaDefinitions: signupSchemaDefinitions,
  publicSettings: (config) => ({ contract: signupManifest.contract, forms: config.forms }),
  wire(backend, config, context: PluginWiringContext) {
    const lambda = backend.signupSubmit.resources.lambda as LambdaFunction;
    const stack = Stack.of(lambda);
    lambda.addEnvironment("PAPYRUS_GRAPHQL_ENDPOINT", context.graphqlEndpoint);
    lambda.addEnvironment("PAPYRUS_SIGNUP_FORMS", config.forms.join(","));
    lambda.addEnvironment("PAPYRUS_SIGNUP_ADDRESS_LIMIT", String(config.addressLimitPerMinute));
    lambda.addToRolePolicy(
      new PolicyStatement({
        effect: Effect.ALLOW,
        actions: ["appsync:GraphQL"],
        resources: [`arn:aws:appsync:${stack.region}:${stack.account}:apis/${context.graphqlApiId}/types/Mutation/fields/createSignupEntry`],
      }),
    );
    if (config.waf) {
      addSignupRateLimit(context.createStack("signup-protection"), {
        graphqlApiArn: `arn:aws:appsync:${stack.region}:${stack.account}:apis/${context.graphqlApiId}`,
        limit: config.addressLimitPerMinute,
      });
    }
  },
};
