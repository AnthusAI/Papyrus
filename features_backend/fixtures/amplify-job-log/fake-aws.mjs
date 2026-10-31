#!/usr/bin/env node
import fs from "node:fs";

const scenario = JSON.parse(fs.readFileSync(process.env.FAKE_AWS_SCENARIO, "utf8").replaceAll("{{LOG_URL}}", process.env.FAKE_LOG_URL ?? ""));
const words = process.argv.slice(2);
const joined = words.join(" ");
const valueOf = (flag) => words[words.indexOf(flag) + 1];
const reply = (value) => process.stdout.write(JSON.stringify(value));

if (joined.startsWith("amplify list-jobs")) {
  reply({ jobSummaries: scenario.jobSummaries });
} else if (joined.startsWith("amplify get-job")) {
  reply({ job: scenario.job });
} else if (joined.startsWith("cloudformation describe-stacks")) {
  reply({ Stacks: scenario.stacks });
} else if (joined.startsWith("cloudformation describe-stack-events")) {
  reply({ StackEvents: scenario.stackEvents[valueOf("--stack-name")] ?? [] });
} else {
  process.stderr.write(`fake aws: unexpected call ${joined}\n`);
  process.exit(2);
}
