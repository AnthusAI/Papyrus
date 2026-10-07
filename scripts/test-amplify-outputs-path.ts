import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { getAmplifyOutputsPath } from "../lib/amplify-outputs-path";

const workingDirectory = fs.mkdtempSync(path.join(os.tmpdir(), "papyrus-outputs-path-"));
const originalDirectory = process.cwd();
delete process.env.PAPYRUS_AMPLIFY_OUTPUTS;
process.chdir(workingDirectory);
const resolvedWorkingDirectory = process.cwd();

try {
  assert.equal(getAmplifyOutputsPath(), path.join(resolvedWorkingDirectory, "amplify_outputs.json"), "defaults to the checkout root when nothing exists");

  fs.mkdirSync(".next");
  fs.writeFileSync(path.join(".next", "amplify_outputs.json"), "{}");
  assert.equal(getAmplifyOutputsPath(), path.join(resolvedWorkingDirectory, ".next", "amplify_outputs.json"), "falls back to the copy shipped in .next");

  fs.writeFileSync("amplify_outputs.json", "{}");
  assert.equal(getAmplifyOutputsPath(), path.join(resolvedWorkingDirectory, "amplify_outputs.json"), "prefers the checkout root copy");

  process.env.PAPYRUS_AMPLIFY_OUTPUTS = "custom/outputs.json";
  assert.equal(getAmplifyOutputsPath(), path.join(resolvedWorkingDirectory, "custom/outputs.json"), "explicit override wins");
  console.log("amplify outputs path tests passed");
} finally {
  process.chdir(originalDirectory);
  fs.rmSync(workingDirectory, { recursive: true, force: true });
}
