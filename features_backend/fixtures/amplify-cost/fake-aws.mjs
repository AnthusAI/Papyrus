#!/usr/bin/env node
import fs from "node:fs";

const scenario = JSON.parse(fs.readFileSync(process.env.FAKE_AWS_SCENARIO, "utf8"));
const words = process.argv.slice(2);
const joined = words.join(" ");
const valueOf = (flag) => words[words.indexOf(flag) + 1];
const reply = (value) => process.stdout.write(JSON.stringify(value));
const metrics = (cost, quantity, unit) => ({ UnblendedCost: { Amount: String(cost), Unit: "USD" }, UsageQuantity: { Amount: String(quantity), Unit: unit } });

if (joined.startsWith("ce get-cost-and-usage")) {
  const period = Object.fromEntries(valueOf("--time-period").split(",").map((pair) => pair.split("=")));
  const results = Object.entries(scenario.costByMonth)
    .filter(([monthStart]) => monthStart >= period.Start && monthStart < period.End)
    .map(([monthStart, groups]) => ({
      TimePeriod: { Start: monthStart, End: monthStart },
      Groups: groups.map((group) => ({ Keys: [group.usageType, group.account], Metrics: metrics(group.cost, group.quantity, group.unit) })),
    }));
  reply({ ResultsByTime: results });
} else if (joined.startsWith("sts get-caller-identity")) {
  reply({ Account: scenario.account });
} else if (joined.startsWith("amplify list-apps")) {
  reply({ apps: scenario.apps.map(({ appId, name }) => ({ appId, name })) });
} else if (joined.startsWith("amplify list-branches")) {
  reply({ branches: scenario.apps.find((app) => app.appId === valueOf("--app-id")).branches.map((branchName) => ({ branchName })) });
} else if (joined.startsWith("amplify list-jobs")) {
  reply({ jobSummaries: scenario.jobs[valueOf("--app-id")] ?? [] });
} else {
  process.stderr.write(`fake aws: unexpected call ${joined}\n`);
  process.exit(2);
}
