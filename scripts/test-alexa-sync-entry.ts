/**
 * The skill sync's real entry points start: `amplify/plugins/alexa/sync/cli.ts` (what `papyrus-app alexa-sync` runs in a site
 * build) and `scripts/alexa/ask-deploy.ts`. Both once used top-level await, which tsx's CJS transform rejects, so the sync never
 * ran (PPY-87c24e). Each prints `{"behaviour": ...}`; with outputs that do not enable the plugin they skip without AWS.
 */
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

function run(entry: string): string {
  const directory = mkdtempSync(path.join(tmpdir(), "alexa-sync-entry-"));
  try {
    const outputs = path.join(directory, "amplify_outputs.json");
    writeFileSync(outputs, "{}");
    return execFileSync(process.execPath, ["--import", "tsx", entry, "--outputs", outputs], { encoding: "utf8" });
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
}

const behaviours: Record<string, () => void> = {
  "the build's sync entry point starts and skips a site without the plugin": () => {
    assert.match(run("amplify/plugins/alexa/sync/cli.ts"), /alexa-sync: skipped, this site does not enable the alexa plugin/);
  },
  "the by-hand sync script starts too": () => {
    assert.match(run("scripts/alexa/ask-deploy.ts"), /alexa-sync: skipped, this site does not enable the alexa plugin/);
  },
};

const requested = process.argv[2];
for (const name of requested === undefined ? Object.keys(behaviours) : [requested]) {
  const behaviour = behaviours[name];
  assert.ok(behaviour, `unknown behaviour "${name}"`);
  behaviour();
  console.log(JSON.stringify({ behaviour: name }));
}
