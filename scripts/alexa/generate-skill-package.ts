/**
 * Writes the Alexa skill package files (`skill.json` and `interactionModels/custom/<locale>.json`) from a resolved `alexa` plugin
 * config and the intent registry. The generator itself lives in `amplify/plugins/alexa/skill-package.ts` (it ships inside the
 * Papyrus package, where site deploys run it); this is the command line.
 *
 *   tsx scripts/alexa/generate-skill-package.ts --config '<json>' --endpoint-arn <arn> --out <dir>
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { resolveAlexaConfig } from "../../amplify/plugins/alexa/config";
import { generateSkillPackage } from "../../amplify/plugins/alexa/skill-package";

export * from "../../amplify/plugins/alexa/skill-package";

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
