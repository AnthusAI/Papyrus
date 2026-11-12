#!/usr/bin/env node
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const previewPort = process.env.PAPYRUS_PREVIEW_PORT?.trim() || "3002";
const previewHostname = process.env.PAPYRUS_PREVIEW_HOSTNAME?.trim() || "127.0.0.1";

const demoOutputsPath = path.join(repositoryRoot, "amplify", "fixtures", "demo-amplify-outputs.json");
const activeOutputsPath = path.join(repositoryRoot, "amplify_outputs.json");
const stashedOutputsPath = path.join(repositoryRoot, "amplify_outputs.json.stashed-by-local-preview");

if (fs.existsSync(activeOutputsPath) && !fs.existsSync(stashedOutputsPath)) {
  fs.renameSync(activeOutputsPath, stashedOutputsPath);
}
fs.copyFileSync(demoOutputsPath, activeOutputsPath);

function restoreStashedOutputs() {
  if (!fs.existsSync(stashedOutputsPath)) {
    fs.rmSync(activeOutputsPath, { force: true });
    return;
  }
  fs.renameSync(stashedOutputsPath, activeOutputsPath);
}

// The sample site's Story types, in the shape withPapyrus inlines from a site's web/projection.json: it names no default, so a new Story has no type; `guide` is offered but has no address.
const previewStoryTypes = {
  storyTypes: { types: ["article", "post", "guide"] },
  urls: { types: { article: { base: "articles" }, post: { base: "posts" } } },
  listings: { types: ["article", "post"] },
  publication: { timeZone: "America/New_York" },
};

const previewEnvironment = {
  ...process.env,
  NEXT_PUBLIC_PAPYRUS_PROJECTION_TYPES: process.env.NEXT_PUBLIC_PAPYRUS_PROJECTION_TYPES ?? JSON.stringify(previewStoryTypes),
  NEXT_PUBLIC_PAPYRUS_LOCAL_PREVIEW: "1",
  PAPYRUS_AMPLIFY_OUTPUTS: activeOutputsPath,
};

console.log(`[papyrus] Local preview: seeded sample data, no AWS. http://${previewHostname}:${previewPort}/newsroom/work`);

const nextProcess = spawn(
  process.execPath,
  [path.join(repositoryRoot, "node_modules", "next", "dist", "bin", "next"), "dev", "--hostname", previewHostname, "-p", previewPort],
  { cwd: repositoryRoot, env: previewEnvironment, stdio: "inherit" },
);
nextProcess.on("exit", (code) => {
  restoreStashedOutputs();
  process.exit(code ?? 0);
});
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => nextProcess.kill(signal));
