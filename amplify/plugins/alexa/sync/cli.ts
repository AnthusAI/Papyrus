/**
 * `papyrus-app alexa-sync` runs this inside a site's Amplify build, after the backend deploy has written `amplify_outputs.json`:
 *
 *   tsx amplify/plugins/alexa/sync/cli.ts [--outputs amplify_outputs.json]
 *
 * It reads `custom.alexa` from the outputs (function ARN, resolved settings, account linking client), and syncs the skill with
 * Amazon. A site without the plugin, or a deploy without the developer credentials in SSM, logs one line and exits 0.
 */
import { readFileSync } from "node:fs";
import { resolveAlexaConfig } from "../config";
import { cognitoClientSecrets, lambdaFunctionPermissions, ssmParameterStore } from "./aws";
import { createSmapiClient, fetchLwaAccessToken } from "./smapi";
import { syncAlexaSkill } from "./sync";

export async function runCli(argv: string[], log: (line: string) => void = console.log): Promise<number> {
  const flag = argv.indexOf("--outputs");
  const outputsPath = flag === -1 ? "amplify_outputs.json" : argv[flag + 1];
  let outputs: { custom?: { alexa?: { functionArn?: string; settings?: Record<string, unknown>; accountLinking?: { userPoolId: string; clientId: string; hostedUiDomain: string } } } };
  try {
    outputs = JSON.parse(readFileSync(outputsPath, "utf8"));
  } catch {
    log(`alexa-sync: skipped, ${outputsPath} could not be read`);
    return 0;
  }
  const alexa = outputs.custom?.alexa;
  if (alexa?.functionArn === undefined || alexa.settings === undefined) {
    log("alexa-sync: skipped, this site does not enable the alexa plugin");
    return 0;
  }
  const config = resolveAlexaConfig({ name: "alexa", ...alexa.settings });
  try {
    await syncAlexaSkill(
      { config, endpointArn: alexa.functionArn, accountLinking: alexa.accountLinking },
      {
        parameters: ssmParameterStore(),
        permissions: lambdaFunctionPermissions(),
        clientSecrets: cognitoClientSecrets(),
        connect: async (credentials) => createSmapiClient(await fetchLwaAccessToken(credentials)),
        log,
      },
    );
    return 0;
  } catch (error) {
    log(`alexa-sync: failed, ${error instanceof Error ? error.message : String(error)}`);
    return 1;
  }
}

// Run directly (the package's compiled cli.js, or cli.ts under tsx): no top-level await, which tsx's CJS transform rejects.
if (/sync\/cli\.(ts|js)$/.test(process.argv[1] ?? "")) {
  void runCli(process.argv.slice(2)).then((code) => process.exit(code));
}
