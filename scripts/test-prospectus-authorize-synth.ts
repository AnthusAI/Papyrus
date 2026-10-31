/**
 * The Prospectus authorize flag changes the synthesized backend only when it is on. Each configuration is synthesized in its own
 * process (a CDK app is one per process) with `scripts/synth-site-backend.mts` and the templates are searched.
 */
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readdirSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const root = join(import.meta.dirname, "..");
const ENDPOINT = "https://abc123defg.execute-api.us-east-1.amazonaws.com/api/";
const work = mkdtempSync(join(tmpdir(), "papyrus-authorize-synth-"));

/** Templates with the values that change on every synth (two clocks) and the asset hashes derived from them masked. */
function synthesize(name: string, backend: string, environment: Record<string, string> = {}): string {
  const out = join(work, name);
  execFileSync(process.execPath, ["--import", "tsx", join(root, "scripts/synth-site-backend.mts"), out, backend], {
    cwd: root,
    env: { ...process.env, ...environment },
    stdio: ["ignore", "pipe", "pipe"],
    maxBuffer: 64 * 1024 * 1024,
  });
  const files: string[] = [];
  const walk = (directory: string) => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      if (entry.isDirectory()) walk(join(directory, entry.name));
      else if (entry.name.endsWith(".template.json")) files.push(join(directory, entry.name));
    }
  };
  walk(out);
  return files.sort().map((file) => readFileSync(file, "utf8")).join("\n").replace(/("(?:secretLastUpdated|Expires)": )\d+/g, "$1TIME").replace(/[0-9a-f]{64}/g, "HASH");
}

try {
  const off = synthesize("off", "{}", { PAPYRUS_PROSPECTUS_ACCOUNTS_ENDPOINT: ENDPOINT });
  const offExplicit = synthesize("off-explicit", '{"features":{"prospectusAuthorize":false}}', { PAPYRUS_PROSPECTUS_ACCOUNTS_ENDPOINT: ENDPOINT });
  assert.equal(offExplicit, off, "an explicit false synthesizes exactly what the default does, with the same endpoint set");
  for (const marker of ["ProspectusAccounts", "PAPYRUS_PROSPECTUS_AUTHORIZE", "execute-api:Invoke"]) {
    assert.equal(off.includes(marker), false, `flag off: no ${marker} in the backend`);
  }

  const on = synthesize("on", '{"features":{"prospectusAuthorize":true}}', { PAPYRUS_PROSPECTUS_ACCOUNTS_ENDPOINT: ENDPOINT });
  for (const marker of ["ProspectusAccounts", "PAPYRUS_PROSPECTUS_AUTHORIZE", "execute-api:Invoke", "abc123defg.execute-api.us-east-1.amazonaws.com"]) {
    assert.ok(on.includes(marker), `flag on: ${marker} is in the backend`);
  }
  assert.ok(on.includes('"SigningServiceName": "execute-api"') || on.includes('"SigningServiceName":"execute-api"'), "the HTTP data source signs for execute-api");
  const pipelineFunctions = (text: string) => text.split('"Type": "AWS::AppSync::FunctionConfiguration"').length - 1;
  assert.ok(pipelineFunctions(on) > pipelineFunctions(off), "flag on: the Prospectus pipeline function is added to the data API");
  console.log("prospectus authorize synth: ok");
} finally {
  rmSync(work, { recursive: true, force: true });
}
