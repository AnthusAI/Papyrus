/**
 * The Alexa skill package, generated from a resolved `alexa` plugin config and the intent registry. Deterministic: the same
 * inputs give the same bytes (sorted intents, sorted keys, a trailing newline), so the content hash the deploy sync compares is
 * stable. Lives under `amplify/` because that folder ships inside `@anthusai/papyrus`, which is where a site's deploy runs it
 * (`scripts/alexa/generate-skill-package.ts` is the command-line wrapper).
 */
import { createHash } from "node:crypto";
import { DEFAULT_SKILL_LOCALES, resolveSiteId, type AlexaConfig } from "./config";
import type { IntentModule, InteractionModelIntent, InteractionModelType } from "./contracts";
import { INTENT_MODULES } from "./intents";

export const SKILL_LOCALE = "en-US";
export const SKILL_MANIFEST_PATH = "skill.json";
export const INTERACTION_MODEL_PATH = interactionModelPath(SKILL_LOCALE);
export const ACCOUNT_LINKING_PATH = "accountLinking.json";

export function interactionModelPath(locale: string): string {
  return `interactionModels/custom/${locale}.json`;
}

export type SkillPackageOptions = {
  /** The skill function's ARN (`custom.alexa.functionArn` in amplify_outputs.json). */
  endpointArn: string;
  modules?: readonly IntentModule[];
};

/** `JSON.stringify` with object keys sorted at every level; arrays keep their order. */
export function stableJson(value: unknown): string {
  const sort = (input: unknown): unknown => {
    if (Array.isArray(input)) return input.map(sort);
    if (input !== null && typeof input === "object") {
      return Object.fromEntries(
        Object.entries(input as Record<string, unknown>)
          .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
          .map(([key, entry]) => [key, sort(entry)]),
      );
    }
    return input;
  };
  return `${JSON.stringify(sort(value), null, 2)}\n`;
}

export function skillLocales(config: AlexaConfig): readonly string[] {
  return config.locales ?? DEFAULT_SKILL_LOCALES;
}

/** The skill's public URLs: from the config, else under the site origin. `undefined` when neither exists. */
export function skillPublicUrls(config: AlexaConfig) {
  const under = (path: string) => (config.siteOrigin === undefined ? undefined : `${config.siteOrigin}${path}`);
  return {
    privacyPolicyUrl: config.privacyPolicyUrl ?? under("/alexa/privacy/"),
    termsOfUseUrl: config.termsOfUseUrl ?? under("/alexa/terms/"),
    smallIconUri: config.iconSmallUri ?? under("/alexa/icon-108.png"),
    largeIconUri: config.iconLargeUri ?? under("/alexa/icon-512.png"),
  };
}

/** What a manifest needs that the config cannot supply, as readable reasons (empty when the manifest can be generated). */
export function missingManifestInputs(config: AlexaConfig): string[] {
  const urls = skillPublicUrls(config);
  const missing: string[] = [];
  if (urls.privacyPolicyUrl === undefined) missing.push("privacyPolicyUrl (or siteOrigin)");
  if (urls.termsOfUseUrl === undefined) missing.push("termsOfUseUrl (or siteOrigin)");
  if (urls.smallIconUri === undefined) missing.push("iconSmallUri (or siteOrigin)");
  if (urls.largeIconUri === undefined) missing.push("iconLargeUri (or siteOrigin)");
  return missing;
}

export function skillManifest(config: AlexaConfig, options: SkillPackageOptions) {
  const missing = missingManifestInputs(config);
  if (missing.length > 0) throw new Error(`The skill manifest needs: ${missing.join(", ")}`);
  const urls = skillPublicUrls(config) as Record<keyof ReturnType<typeof skillPublicUrls>, string>;
  const locales = skillLocales(config);
  const keywords = config.keywords ?? [config.invocationName, "news"];
  return {
    manifest: {
      manifestVersion: "1.0",
      publishingInformation: {
        locales: Object.fromEntries(
          locales.map((locale) => [
            locale,
            {
              name: config.skillName,
              summary: `The latest stories from ${config.skillName}.`,
              description: `Hear the latest published stories from ${config.skillName}, read aloud, and see them on screens that have one.`,
              examplePhrases: [`Alexa, open ${config.invocationName}`],
              keywords,
              smallIconUri: urls.smallIconUri,
              largeIconUri: urls.largeIconUri,
            },
          ]),
        ),
        isAvailableWorldwide: true,
        category: "NEWS",
        distributionCountries: [],
        testingInstructions: `Say "Alexa, open ${config.invocationName}" to hear the latest published stories. No account is needed${config.accountLinking ? "; linking an account is optional" : ""}.`,
      },
      apis: { custom: { endpoint: { uri: options.endpointArn }, interfaces: [{ type: "ALEXA_PRESENTATION_APL" }] } },
      privacyAndCompliance: {
        allowsPurchases: false,
        usesPersonalInfo: config.accountLinking,
        isChildDirected: false,
        isExportCompliant: true,
        containsAds: false,
        locales: Object.fromEntries(locales.map((locale) => [locale, { privacyPolicyUrl: urls.privacyPolicyUrl, termsOfUseUrl: urls.termsOfUseUrl }])),
      },
    },
  };
}

export function interactionModel(config: AlexaConfig, modules: readonly IntentModule[] = INTENT_MODULES) {
  const intents: InteractionModelIntent[] = [];
  const types = new Map<string, InteractionModelType>();
  for (const intentModule of modules) {
    if (intentModule.interactionModel === undefined) continue;
    intents.push(intentModule.interactionModel.intent);
    for (const type of intentModule.interactionModel.types ?? []) {
      const existing = types.get(type.name);
      if (existing !== undefined && stableJson(existing) !== stableJson(type)) throw new Error(`Slot type "${type.name}" is defined twice with different values`);
      types.set(type.name, type);
    }
  }
  const names = intents.map((intent) => intent.name);
  const duplicate = names.find((name, index) => names.indexOf(name) !== index);
  if (duplicate !== undefined) throw new Error(`Intent "${duplicate}" is defined by two intent modules`);
  intents.sort((left, right) => (left.name < right.name ? -1 : 1));
  return {
    interactionModel: {
      languageModel: {
        invocationName: config.invocationName,
        intents,
        types: [...types.values()].sort((left, right) => (left.name < right.name ? -1 : 1)),
      },
    },
  };
}

/** What the Cognito task publishes as `custom.alexa.accountLinking` in amplify_outputs.json (docs/alexa.md). */
export type AccountLinkingOutputs = {
  userPoolId: string;
  /** The Alexa app client's id. */
  clientId: string;
  /** The hosted UI domain prefix (for example `papyrus-pilobol-us-cms`) or a full host name. */
  hostedUiDomain: string;
};

/** The hosted UI origin: a bare prefix becomes `<prefix>.auth.<region>.amazoncognito.com`, the region read from the pool id. */
export function hostedUiOrigin(outputs: AccountLinkingOutputs): string {
  if (outputs.hostedUiDomain.includes(".")) return `https://${outputs.hostedUiDomain}`;
  const region = outputs.userPoolId.split("_")[0];
  return `https://${outputs.hostedUiDomain}.auth.${region}.amazoncognito.com`;
}

/** The body of `PUT /v1/skills/{id}/stages/development/accountLinkingClient`. Linking stays optional (`skipOnEnablement`). */
export function accountLinkingRequest(outputs: AccountLinkingOutputs, clientSecret: string) {
  const origin = hostedUiOrigin(outputs);
  return {
    accountLinkingRequest: {
      type: "AUTH_CODE",
      authorizationUrl: `${origin}/oauth2/authorize`,
      accessTokenUrl: `${origin}/oauth2/token`,
      clientId: outputs.clientId,
      clientSecret,
      scopes: ["openid", "email", "profile"],
      accessTokenScheme: "HTTP_BASIC",
      skipOnEnablement: true,
    },
  };
}

/** The package as `relative path -> file text`. */
export function generateSkillPackage(config: AlexaConfig, options: SkillPackageOptions): Record<string, string> {
  const files: Record<string, string> = { [SKILL_MANIFEST_PATH]: stableJson(skillManifest(config, options)) };
  const model = stableJson(interactionModel(config, options.modules));
  for (const locale of skillLocales(config)) files[interactionModelPath(locale)] = model;
  return files;
}

export function contentHash(...parts: string[]): string {
  const hash = createHash("sha256");
  for (const part of parts) hash.update(`${part.length}:${part}`);
  return hash.digest("hex");
}

export { resolveSiteId };
