// Measures how long a finished release's data stack update took, for the GSI release budget (scripts/data/gsi-deploy-measurements.json).
// Read-only: it calls `aws cloudformation describe-stack-events` on the root backend stack with the AWS profile and region in the environment.
// Usage: AWS_PROFILE=... AWS_REGION=... tsx scripts/measure-gsi-deploy.ts --root-stack NAME --index-creations N --label TEXT [--date YYYY-MM-DD] [--append]
// N is the number of indexes the release created on existing tables (what `tsx scripts/check-gsi-ledger.ts` printed for it).
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { dataStackSeconds, parseMeasurementFile, secondsPerCreation, type StackEvent } from "./lib/gsi-release-budget";

const args = process.argv.slice(2);
const option = (name: string) => (args.includes(name) ? args[args.indexOf(name) + 1] : undefined);
const required = (name: string) => option(name) ?? (() => { throw new Error(`measure-gsi-deploy: ${name} is required.`); })();

const rootStack = required("--root-stack");
const indexCreations = Number(required("--index-creations"));
const label = required("--label");
const date = option("--date") ?? new Date().toISOString().slice(0, 10);
const output = execFileSync("aws", ["cloudformation", "describe-stack-events", "--stack-name", rootStack, "--output", "json"], { encoding: "utf8", maxBuffer: 1 << 28 });
const events: StackEvent[] = JSON.parse(output).StackEvents;
const entry = { date, label, indexCreations, deploySeconds: dataStackSeconds(events) };
console.log(`${entry.deploySeconds} s for ${indexCreations} index creations: ${Math.round(secondsPerCreation(entry))} s per creation.`);
if (args.includes("--append")) {
  const file = new URL("./data/gsi-deploy-measurements.json", import.meta.url);
  const data = JSON.parse(readFileSync(file, "utf8"));
  data.measurements.push(entry);
  parseMeasurementFile(data);
  writeFileSync(file, `${JSON.stringify(data, null, 2)}\n`);
  console.log("Appended to scripts/data/gsi-deploy-measurements.json.");
} else {
  console.log(JSON.stringify(entry, null, 2));
}
