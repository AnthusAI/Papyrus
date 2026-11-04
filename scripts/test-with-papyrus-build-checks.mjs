import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { withPapyrus, isAmplifyBuild, engineVersionEnvironment } from "../packages/papyrus/src/with-papyrus.mjs";

const keys = ["AWS_APP_ID", "AWS_BRANCH", "PAPYRUS_NEXT_BUILD_CHECKS"];
function withEnv(env, fn) {
  const saved = Object.fromEntries(keys.map((k) => [k, process.env[k]]));
  for (const k of keys) delete process.env[k];
  Object.assign(process.env, env);
  try {
    return fn();
  } finally {
    for (const k of keys) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
}

const amplify = { AWS_APP_ID: "d123", AWS_BRANCH: "main" };

const skipped = withEnv(amplify, () => withPapyrus({}));
assert.equal(skipped.typescript.ignoreBuildErrors, true, "Amplify skips the type-check");
assert.equal(skipped.eslint.ignoreDuringBuilds, true, "Amplify skips lint");
assert.equal(withEnv({ AWS_BRANCH: "main" }, () => isAmplifyBuild()), true);

const local = withEnv({}, () => withPapyrus({}));
assert.equal(local.typescript, undefined, "outside Amplify the checks run");
assert.equal(local.eslint, undefined);

const siteWins = withEnv(amplify, () =>
  withPapyrus({ typescript: { ignoreBuildErrors: false, tsconfigPath: "x.json" }, eslint: { ignoreDuringBuilds: false } }),
);
assert.equal(siteWins.typescript.ignoreBuildErrors, false, "site config wins");
assert.equal(siteWins.typescript.tsconfigPath, "x.json");
assert.equal(siteWins.eslint.ignoreDuringBuilds, false);

const overridden = withEnv({ ...amplify, PAPYRUS_NEXT_BUILD_CHECKS: "1" }, () => withPapyrus({}));
assert.equal(overridden.typescript, undefined, "override restores the checks");
assert.equal(overridden.eslint, undefined);

// The installed package tells /.well-known/papyrus-site.json its version; a checkout of the engine tells nothing.
const staged = fs.mkdtempSync(path.join(os.tmpdir(), "engine-version-"));
fs.writeFileSync(path.join(staged, "package.json"), JSON.stringify({ name: "@anthusai/papyrus", version: "5.81.0" }));
fs.writeFileSync(path.join(staged, "other.json"), JSON.stringify({ name: "papyrus", version: "1.0.0" }));
assert.deepEqual(engineVersionEnvironment(path.join(staged, "package.json")), { PAPYRUS_ENGINE_VERSION: "5.81.0" });
assert.deepEqual(engineVersionEnvironment(path.join(staged, "other.json")), {}, "not the published package");
assert.deepEqual(engineVersionEnvironment(path.join(staged, "missing.json")), {});
assert.deepEqual(engineVersionEnvironment(), {}, "the engine checkout has no published version");
fs.rmSync(staged, { recursive: true, force: true });

console.log("with-papyrus build checks tests passed");
