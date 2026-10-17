import assert from "node:assert/strict";
import {
  withPapyrus,
  DEFAULT_STATIC_GENERATION_WORKERS,
  DEFAULT_STATIC_GENERATION_CONCURRENCY,
  DEFAULT_STATIC_GENERATION_RETRY_COUNT,
} from "../packages/papyrus/src/with-papyrus.mjs";

delete process.env.PAPYRUS_STATIC_GENERATION_WORKERS;
delete process.env.PAPYRUS_STATIC_GENERATION_CONCURRENCY;

const defaults = withPapyrus({}).experimental;
assert.equal(defaults.cpus, DEFAULT_STATIC_GENERATION_WORKERS);
assert.ok(defaults.cpus >= 2 && defaults.cpus <= 4, "conservative worker default");
assert.equal(defaults.staticGenerationMaxConcurrency, DEFAULT_STATIC_GENERATION_CONCURRENCY);
assert.ok(defaults.staticGenerationMaxConcurrency < 8, "below Next's default of 8");
assert.ok(defaults.staticGenerationRetryCount >= 3);
assert.equal(defaults.staticGenerationRetryCount, DEFAULT_STATIC_GENERATION_RETRY_COUNT);
assert.equal(defaults.devtoolSegmentExplorer, false);

process.env.PAPYRUS_STATIC_GENERATION_WORKERS = "4";
process.env.PAPYRUS_STATIC_GENERATION_CONCURRENCY = "6";
const overridden = withPapyrus({}).experimental;
assert.equal(overridden.cpus, 4);
assert.equal(overridden.staticGenerationMaxConcurrency, 6);

process.env.PAPYRUS_STATIC_GENERATION_WORKERS = "not-a-number";
assert.equal(withPapyrus({}).experimental.cpus, DEFAULT_STATIC_GENERATION_WORKERS, "invalid override ignored");
delete process.env.PAPYRUS_STATIC_GENERATION_WORKERS;
delete process.env.PAPYRUS_STATIC_GENERATION_CONCURRENCY;

const siteOverride = withPapyrus({ experimental: { cpus: 1, ppr: false } }).experimental;
assert.equal(siteOverride.cpus, 1, "a site's own experimental setting wins");
assert.equal(siteOverride.ppr, false);
assert.equal(siteOverride.staticGenerationMaxConcurrency, DEFAULT_STATIC_GENERATION_CONCURRENCY);

console.log("with-papyrus static generation tests passed");
