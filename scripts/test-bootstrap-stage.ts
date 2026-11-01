/**
 * CloudFormation creates at most 2,500 resources in one stack operation, nested stacks included. The full backend
 * is more than that, so a brand-new site's first `ampx pipeline-deploy` runs with `PAPYRUS_BOOTSTRAP_STAGE=1`.
 * This synthesizes the real backend (in a child process, because Amplify allows one backend per process) with the
 * switch on and counts every resource across the root and nested templates.
 */
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { OPTIONAL_MODEL_GROUPS } from "../amplify/data/schema";

const CLOUDFORMATION_OPERATION_LIMIT = 2500;
// Headroom for plugins and features a site turns on, and for models added later.
const BOOTSTRAP_BUDGET = 2000;

const outputDirectory = mkdtempSync(path.join(tmpdir(), "papyrus-bootstrap-"));
try {
  const synth = spawnSync("npx", ["tsx", "scripts/synth-site-backend.mts", outputDirectory, '{"productionAppId":"","brandId":"bootstrap-test"}'], {
    cwd: path.resolve(import.meta.dirname, ".."),
    env: { ...process.env, PAPYRUS_BOOTSTRAP_STAGE: "1" },
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
  });
  assert.equal(synth.status, 0, `${synth.stdout}\n${synth.stderr}`);

  let resources = 0;
  const modelStacks: string[] = [];
  for (const file of readdirSync(outputDirectory).filter((name) => name.endsWith(".template.json"))) {
    resources += Object.keys(JSON.parse(readFileSync(path.join(outputDirectory, file), "utf8")).Resources ?? {}).length;
    const model = /PapyrusCmsApi(.+?)[0-9A-F]{8}\.nested\.template\.json$/.exec(file);
    if (model) modelStacks.push(model[1]);
  }

  assert.ok(resources < BOOTSTRAP_BUDGET, `bootstrap stage has ${resources} resources; keep it under ${BOOTSTRAP_BUDGET} (CloudFormation fails at ${CLOUDFORMATION_OPERATION_LIMIT})`);
  for (const modelName of Object.values(OPTIONAL_MODEL_GROUPS).flat()) {
    assert.ok(!modelStacks.includes(modelName), `${modelName} is deferred to the second deploy`);
  }
  for (const core of ["UserProfile", "Item", "Reference", "Message"]) {
    assert.ok(modelStacks.includes(core), `${core} is created by the first deploy`);
  }
  const templates = readdirSync(outputDirectory).filter((name) => name.endsWith(".template.json"));
  assert.ok(!templates.some((name) => /reprojectondeploy/i.test(name)), "the bootstrap stage creates no post-deploy render");
  console.log(`bootstrap stage: ${resources} resources, ${modelStacks.length} model stacks`);
  console.log("bootstrap stage tests passed");
} finally {
  rmSync(outputDirectory, { recursive: true, force: true });
}
