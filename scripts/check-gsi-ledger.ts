// CI check: compares amplify/data/schema.ts with the last stable release tag (or --base FILE) and fails on the GSI ledger rules.
// Usage: tsx scripts/check-gsi-ledger.ts [--base FILE] [--current FILE]
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { compareLedgers, parseLedger } from "./lib/gsi-ledger";

const args = process.argv.slice(2);
const option = (name: string) => (args.includes(name) ? args[args.indexOf(name) + 1] : undefined);
const git = (...gitArgs: string[]) => execFileSync("git", gitArgs, { encoding: "utf8", maxBuffer: 1 << 26, stdio: ["ignore", "pipe", "pipe"] });

function baselineFromLastRelease(): { label: string; source: string } | undefined {
  const stable = (tag: string) => /^v\d+\.\d+\.\d+$/.test(tag);
  const newest = (tags: string[]) =>
    tags.filter(stable).sort((a, b) => {
      const [x, y] = [a, b].map((tag) => tag.slice(1).split(".").map(Number));
      return y[0] - x[0] || y[1] - x[1] || y[2] - x[2];
    })[0];
  let tag = newest(git("tag", "--list", "v*").split("\n"));
  if (!tag) {
    // A shallow CI checkout carries no tags: ask the remote for the newest stable one and fetch only that.
    tag = newest(git("ls-remote", "--tags", "origin", "v*").split("\n").map((line) => line.split("refs/tags/")[1] ?? ""));
    if (tag) git("fetch", "--depth=1", "origin", "tag", tag);
  }
  return tag ? { label: tag, source: git("show", `${tag}:amplify/data/schema.ts`) } : undefined;
}

const baseFile = option("--base");
const base = baseFile ? { label: baseFile, source: readFileSync(baseFile, "utf8") } : baselineFromLastRelease();
const current = parseLedger(readFileSync(option("--current") ?? "amplify/data/schema.ts", "utf8"));
if (!base) console.log("GSI ledger: no release tag found; only the table-size limits are checked.");
else console.log(`GSI ledger: comparing with ${base.label}`);
const report = compareLedgers(base ? parseLedger(base.source) : undefined, current);
for (const line of report.releaseOrder) console.log(`  ${line}`);
for (const warning of report.warnings) console.warn(`WARNING: ${warning}`);
for (const failure of report.failures) console.error(`FAIL: ${failure}`);
if (report.failures.length) process.exit(1);
console.log("GSI ledger: ok");
