/**
 * Builds the Alexa skill package files (`skill.json` and `interactionModels/custom/en-US.json`) from a resolved `alexa` plugin
 * config and the intent registry. Deterministic: the same inputs give the same bytes (sorted intents, sorted keys, a trailing
 * newline), so the package in Git can be diffed and CI can check that it is current.
 *
 *   tsx scripts/alexa/generate-skill-package.ts --config '<json>' --endpoint-arn <arn> --out <dir>
 *
 * Skeleton: the manifest has the publishing information and the endpoint; privacy URLs, APL interfaces and account linking are
 * added by the tasks that own them (docs/alexa.md).
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { resolveAlexaConfig, type AlexaConfig } from "../../amplify/plugins/alexa/config";
import type { IntentModule, InteractionModelIntent, InteractionModelType } from "../../amplify/plugins/alexa/contracts";
import { INTENT_MODULES } from "../../amplify/plugins/alexa/intents";

export const SKILL_LOCALE = "en-US";
export const SKILL_MANIFEST_PATH = "skill.json";
export const INTERACTION_MODEL_PATH = `interactionModels/custom/${SKILL_LOCALE}.json`;

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

export function skillManifest(config: AlexaConfig, options: SkillPackageOptions) {
  return {
    manifest: {
      manifestVersion: "1.0",
      publishingInformation: {
        locales: {
          [SKILL_LOCALE]: {
            name: config.skillName,
            summary: `The latest stories from ${config.skillName}.`,
            description: `Hear the latest published stories from ${config.skillName}.`,
            examplePhrases: [`Alexa, open ${config.invocationName}`],
          },
        },
        isAvailableWorldwide: true,
        category: "NEWS",
        distributionCountries: [],
      },
      apis: { custom: { endpoint: { uri: options.endpointArn } } },
      privacyAndCompliance: { allowsPurchases: false, usesPersonalInfo: false, isChildDirected: false, isExportCompliant: true, containsAds: false },
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

/** The package as `relative path -> file text`. */
export function generateSkillPackage(config: AlexaConfig, options: SkillPackageOptions): Record<string, string> {
  return {
    [SKILL_MANIFEST_PATH]: stableJson(skillManifest(config, options)),
    [INTERACTION_MODEL_PATH]: stableJson(interactionModel(config, options.modules)),
  };
}

export function writeSkillPackage(directory: string, files: Record<string, string>): void {
  for (const [relative, text] of Object.entries(files)) {
    const target = join(directory, relative);
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, text);
  }
}

function argument(name: string): string {
  const index = process.argv.indexOf(`--${name}`);
  const value = index === -1 ? undefined : process.argv[index + 1];
  if (value === undefined) throw new Error(`Missing --${name}`);
  return value;
}

if (process.argv[1]?.endsWith("generate-skill-package.ts")) {
  const config = resolveAlexaConfig({ name: "alexa", ...JSON.parse(argument("config")) });
  writeSkillPackage(argument("out"), generateSkillPackage(config, { endpointArn: argument("endpoint-arn") }));
}
