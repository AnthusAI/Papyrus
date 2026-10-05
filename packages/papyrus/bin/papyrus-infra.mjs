#!/usr/bin/env node
/**
 * papyrus-infra synth --site infra/site.json [--out cdk.out]
 * Synthesizes the app-shell stack for a publication from its own site.json
 * (SPIKE, PPY-82be6c). Synth only: deploying is a separate, reviewed step.
 */
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

let AmplifyAppShellStack;
try {
  ({ AmplifyAppShellStack } = await import("../infra/index.js"));
} catch (error) {
  // infra/index.js explains the missing optional peers; print it without a stack trace.
  console.error(`papyrus-infra: ${error instanceof Error ? error.message : error}`);
  process.exit(1);
}

// aws-cdk-lib is an optional peer: resolve it from the publication's infra/ package (cwd).
const { App } = createRequire(path.join(process.cwd(), "noop.js"))("aws-cdk-lib");

const args = process.argv.slice(2);
const opt = (name, fallback) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 ? args[i + 1] : fallback;
};
if (args[0] !== "synth") {
  console.error("Usage: papyrus-infra synth --site infra/site.json [--out cdk.out]");
  process.exit(args[0] ? 1 : 0);
}
const config = JSON.parse(fs.readFileSync(path.resolve(opt("site", "infra/site.json")), "utf8"));
const app = new App({ outdir: path.resolve(opt("out", "cdk.out")) });
new AmplifyAppShellStack(app, `AmplifyAppShell-${config.siteId}`, config, {
  env: { account: opt("account", "335163751677"), region: opt("region", "us-east-1") },
  stackName: `amplify-app-shell-${config.siteId}`,
});
app.synth();
console.log(`synthesized amplify-app-shell-${config.siteId} -> ${path.resolve(opt("out", "cdk.out"))}`);
