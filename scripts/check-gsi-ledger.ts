// CI check: compares the schema sources (amplify/data/schema.ts and every plugin's and function's schema.ts) with the last stable release tag
// (or --base FILE; it fails when no tag is available) and fails on the GSI ledger rules. --base and --current each name one file instead.
// The release budget (scripts/lib/gsi-release-budget.ts) comes from scripts/data/gsi-deploy-measurements.json and the build timeout every site gets by default
// (cms.buildTimeoutMinutes, 120); --build-timeout MINUTES checks against a shorter one.
// Usage: tsx scripts/check-gsi-ledger.ts [--base FILE] [--current FILE] [--build-timeout MINUTES] [--measurements FILE]
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { DEFAULT_BUILD_TIMEOUT_MINUTES } from "../infra/amplify-app-shell/lib/site-config";
import { parseMeasurementFile, releaseBudget } from "./lib/gsi-release-budget";
import { compareLedgers, parseLedger, parseLedgers, SCHEMA_SOURCE, type Ledger } from "./lib/gsi-ledger";

const args = process.argv.slice(2);
const option = (name: string) => (args.includes(name) ? args[args.indexOf(name) + 1] : undefined);
const git = (...gitArgs: string[]) => execFileSync("git", gitArgs, { encoding: "utf8", maxBuffer: 1 << 26, stdio: ["ignore", "pipe", "pipe"] });

function baselineFromLastRelease(): { label: string; ledger: Ledger } {
  const [tag] = git("tag", "--list", "v*")
    .split("\n")
    .filter((name) => /^v\d+\.\d+\.\d+$/.test(name))
    .sort((a, b) => {
      const [x, y] = [a, b].map((name) => name.slice(1).split(".").map(Number));
      return y[0] - x[0] || y[1] - x[1] || y[2] - x[2];
    });
  if (!tag) throw new Error("GSI ledger: no stable release tag (vX.Y.Z) in this checkout; fetch tags (CI: actions/checkout with fetch-depth: 0) before running this check.");
  const paths = git("ls-tree", "-r", "--name-only", tag, "--", "amplify").split("\n").filter((path) => SCHEMA_SOURCE.test(path));
  return { label: tag, ledger: parseLedgers(paths.map((path) => ({ path, source: git("show", `${tag}:${path}`) }))) };
}

function currentSchemaSources(): Ledger {
  const paths = git("ls-files", "--cached", "--others", "--exclude-standard", "--", "amplify").split("\n").filter((path) => SCHEMA_SOURCE.test(path));
  return parseLedgers(paths.map((path) => ({ path, source: readFileSync(path, "utf8") })));
}

const baseFile = option("--base");
const currentFile = option("--current");
const base = baseFile ? { label: baseFile, ledger: parseLedger(readFileSync(baseFile, "utf8")) } : baselineFromLastRelease();
const current = currentFile ? parseLedger(readFileSync(currentFile, "utf8")) : currentSchemaSources();
console.log(`GSI ledger: comparing with ${base.label}`);
const measurements = parseMeasurementFile(JSON.parse(readFileSync(option("--measurements") ?? new URL("./data/gsi-deploy-measurements.json", import.meta.url), "utf8")));
const buildTimeout = option("--build-timeout") === undefined ? DEFAULT_BUILD_TIMEOUT_MINUTES : Number(option("--build-timeout"));
if (!Number.isInteger(buildTimeout) || buildTimeout < 5) throw new Error(`GSI ledger: --build-timeout must be a whole number of minutes, at least 5, got ${option("--build-timeout")}`);
const report = compareLedgers(base.ledger, current, releaseBudget(measurements, buildTimeout));
if (report.estimate) console.log(`  ${report.estimate}`);
for (const line of report.slots) console.log(`  ${line}`);
for (const line of report.releaseOrder) console.log(`  ${line}`);
for (const warning of report.warnings) console.warn(`WARNING: ${warning}`);
for (const failure of report.failures) console.error(`FAIL: ${failure}`);
if (report.failures.length) process.exit(1);
console.log("GSI ledger: ok");
