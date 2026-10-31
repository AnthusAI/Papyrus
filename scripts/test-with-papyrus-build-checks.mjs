import assert from "node:assert/strict";
import { withPapyrus, isAmplifyBuild } from "../packages/papyrus/src/with-papyrus.mjs";

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

console.log("with-papyrus build checks tests passed");
