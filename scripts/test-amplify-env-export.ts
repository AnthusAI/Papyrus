import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

// The SSR build spec copies only an allow-listed set of Amplify branch variables into
// .env.production. Anything not listed never reaches the server at runtime.
const SPECS = ["amplify.yml", "docs/hosting/amplify-ssr.yml.example"];
const EXPORTED = {
  PAPYRUS_CONTENT_SOURCE: "published",
  PAPYRUS_CURATION_UPSTREAM_URL: "https://lab.example.test",
  PAPYRUS_CURATION_PUBLICATION_ID: "demo-publication",
  PAPYRUS_REVALIDATE_SECRET_PARAMETER: "/papyrus/demo/revalidate-secret",
};
const NOT_EXPORTED = { AWS_SECRET_ACCESS_KEY: "must-not-leak", UNRELATED_SETTING: "no" };

const childEnvironment: NodeJS.ProcessEnv = { NODE_ENV: "test", PATH: process.env.PATH ?? "/usr/bin:/bin", ...EXPORTED, ...NOT_EXPORTED };

for (const spec of SPECS) {
  const line = fs.readFileSync(spec, "utf8").split("\n").find((candidate) => candidate.includes(">> .env.production"));
  assert.ok(line, `${spec}: has an env export line`);
  const command = line.trim().replace(/^-\s+/, "");
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "papyrus-env-export-"));
  try {
    execFileSync("sh", ["-c", command], {
      cwd: directory,
      env: childEnvironment,
    });
    const written = fs.readFileSync(path.join(directory, ".env.production"), "utf8");
    for (const [name, value] of Object.entries(EXPORTED)) {
      assert.ok(written.includes(`${name}=${value}`), `${spec}: exports ${name}`);
    }
    for (const name of Object.keys(NOT_EXPORTED)) {
      assert.equal(written.includes(name), false, `${spec}: does not export ${name}`);
    }
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
}
console.log("amplify env export tests passed");
