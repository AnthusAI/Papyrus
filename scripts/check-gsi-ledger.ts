// CI check: compares amplify/data/schema.ts with the last stable release tag (or --base FILE; it fails when no tag is available) and fails on the GSI ledger rules.
// Usage: tsx scripts/check-gsi-ledger.ts [--base FILE] [--current FILE]
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { compareLedgers, parseLedger } from "./lib/gsi-ledger";

const args = process.argv.slice(2);
const option = (name: string) => (args.includes(name) ? args[args.indexOf(name) + 1] : undefined);
const git = (...gitArgs: string[]) => execFileSync("git", gitArgs, { encoding: "utf8", maxBuffer: 1 << 26, stdio: ["ignore", "pipe", "pipe"] });

function baselineFromLastRelease(): { label: string; source: string } {
  const [tag] = git("tag", "--list", "v*")
    .split("\n")
    .filter((name) => /^v\d+\.\d+\.\d+$/.test(name))
    .sort((a, b) => {
      const [x, y] = [a, b].map((name) => name.slice(1).split(".").map(Number));
      return y[0] - x[0] || y[1] - x[1] || y[2] - x[2];
    });
  if (!tag) throw new Error("GSI ledger: no stable release tag (vX.Y.Z) in this checkout; fetch tags (CI: actions/checkout with fetch-depth: 0) before running this check.");
  return { label: tag, source: git("show", `${tag}:amplify/data/schema.ts`) };
}

const baseFile = option("--base");
const base = baseFile ? { label: baseFile, source: readFileSync(baseFile, "utf8") } : baselineFromLastRelease();
const current = parseLedger(readFileSync(option("--current") ?? "amplify/data/schema.ts", "utf8"));
console.log(`GSI ledger: comparing with ${base.label}`);
const report = compareLedgers(parseLedger(base.source), current);
for (const line of report.slots) console.log(`  ${line}`);
for (const line of report.releaseOrder) console.log(`  ${line}`);
for (const warning of report.warnings) console.warn(`WARNING: ${warning}`);
for (const failure of report.failures) console.error(`FAIL: ${failure}`);
if (report.failures.length) process.exit(1);
console.log("GSI ledger: ok");
