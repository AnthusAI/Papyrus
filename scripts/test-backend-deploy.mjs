/**
 * papyrus-infra backend-deploy runs one ampx pipeline-deploy per cost tag wave until the root stack says the tags are
 * complete (infra/amplify-app-shell/features/cost-tags.feature, "Cost tags arrive in waves"). No AWS: the deploy and the
 * stack output are fakes that behave as the backend does (amplify/cost-tag-waves.ts).
 */
import assert from "node:assert/strict";
import { deployMinutes, firstPassWave, MAX_PASSES, parseWaveOutput, runBackendDeployPasses } from "../packages/papyrus/src/backend-deploy.mjs";

/** A deployed backend whose plan has `waves` waves, starting from `output` (the PapyrusCostTagWave value, or undefined). */
function fakeBackend(waves, output) {
  let current = output;
  const deployed = [];
  return {
    deployed,
    readWave: () => parseWaveOutput(current),
    deploy: (wave) => {
      deployed.push(wave);
      if (wave === null) return; // no wave: the backend as it was, no output
      const reached = wave === "all" ? waves : Math.min(Number(wave), waves);
      current = reached >= waves ? "complete" : `${reached}/${waves}`;
    },
  };
}

// The output is "W/N" or "complete"; anything else is refused rather than guessed at.
assert.equal(parseWaveOutput(undefined), null);
assert.deepEqual(parseWaveOutput("complete"), { complete: true });
assert.deepEqual(parseWaveOutput("2/4"), { complete: false, wave: 2, waves: 4 });
assert.throws(() => parseWaveOutput("two"), /not "W\/N" or "complete"/);

// Scenario: a site whose backend has no cost tags yet deploys the release alone, then every wave, in one build.
{
  const backend = fakeBackend(3, undefined);
  assert.deepEqual(runBackendDeployPasses(backend), [null, "1", "2", "3"]);
  assert.equal(firstPassWave(null), null);
}

// Scenario: once the tags are complete, a deploy is one pass, as before.
{
  const backend = fakeBackend(3, "complete");
  assert.deepEqual(runBackendDeployPasses(backend), ["all"]);
  assert.equal(firstPassWave({ complete: true }), "all");
}

// Scenario: a stack part-way through deploys the release at the wave it has, then goes on, never back.
{
  const backend = fakeBackend(4, "2/4");
  assert.deepEqual(runBackendDeployPasses(backend), ["2", "3", "4"]);
}

// A failed pass fails the build (Amplify rolls back that one operation); the next build resumes.
{
  const backend = fakeBackend(3, undefined);
  const failing = { readWave: backend.readWave, deploy: (wave) => { if (wave === "2") throw new Error("rolled back"); backend.deploy(wave); } };
  assert.throws(() => runBackendDeployPasses(failing), /rolled back/);
  // The stack kept wave 1; the next build deploys the release at wave 1 and goes on.
  assert.deepEqual(runBackendDeployPasses(backend), ["1", "2", "3"]);
}

// Scenario: a wave starts only if it fits in the build; the rest wait for the next build.
{
  const backend = fakeBackend(3, undefined);
  let clock = 0;
  const timed = { readWave: backend.readWave, deploy: (wave) => { clock += 10; backend.deploy(wave); }, now: () => clock, minutes: 20 };
  assert.deepEqual(runBackendDeployPasses(timed), [null, "1"], "two 10-minute passes fit in 20 minutes, a third does not");
  clock = 0;
  assert.deepEqual(runBackendDeployPasses(timed), ["1", "2"]);
  clock = 0;
  assert.deepEqual(runBackendDeployPasses(timed), ["2", "3"]);
  assert.deepEqual(backend.readWave(), { complete: true });
  // The build timeout is Amplify's (30 minutes, or _BUILD_TIMEOUT), less 10 for the frontend build and setup.
  assert.equal(deployMinutes({}), 20);
  assert.equal(deployMinutes({ _BUILD_TIMEOUT: "60" }), 50);
}

// A backend on a Papyrus without waves leaves no output after a wave pass: refused, not looped.
{
  const deployed = [];
  assert.throws(() => runBackendDeployPasses({ readWave: () => null, deploy: (wave) => deployed.push(wave) }), /no PapyrusCostTagWave output/);
  assert.deepEqual(deployed, [null, "1"]);
}

// A plan that never completes stops at MAX_PASSES.
{
  let wave = 0;
  assert.throws(
    () => runBackendDeployPasses({ readWave: () => (wave ? { complete: false, wave, waves: 99 } : null), deploy: (asked) => { wave = Number(asked); } }),
    new RegExp(`not complete after ${MAX_PASSES} passes`),
  );
}

console.log("backend-deploy tests passed");
