import { spawnSync } from "node:child_process";

const COST_EXPLORER_REGION = "us-east-1";
const AMPLIFY_SERVICE_NAME = "AWS Amplify";
const BUDGET_NAME = "papyrus-amplify-monthly";
const ALERT_TOPIC_NAME = "papyrus-amplify-cost-alerts";
const ALERT_EMAIL_PARAMETER_NAME = "/papyrus/cost/amplify-alert-email";
const THRESHOLD_QUANTILE = 0.75;
const SECONDS_PER_BILLED_MINUTE = 60;

export function runAwsJson(awsArguments) {
  const completed = spawnSync("aws", [...awsArguments, "--output", "json"], { encoding: "utf8", maxBuffer: 256 * 1024 * 1024 });
  if (completed.status !== 0) {
    throw new Error(`aws ${awsArguments.slice(0, 2).join(" ")} failed: ${(completed.stderr || completed.stdout).trim()}`);
  }
  return completed.stdout.trim() === "" ? {} : JSON.parse(completed.stdout);
}

function monthKey(date) {
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`;
}

function firstOfMonth(year, monthIndex) {
  return new Date(Date.UTC(year, monthIndex, 1));
}

export function planMonths({ months, through, today = new Date() }) {
  const anchor = through ? firstOfMonth(Number(through.slice(0, 4)), Number(through.slice(5, 7)) - 1) : firstOfMonth(today.getUTCFullYear(), today.getUTCMonth());
  const currentMonthStart = firstOfMonth(today.getUTCFullYear(), today.getUTCMonth());
  const planned = [];
  for (let offset = months - 1; offset >= 0; offset -= 1) {
    const start = firstOfMonth(anchor.getUTCFullYear(), anchor.getUTCMonth() - offset);
    const end = firstOfMonth(start.getUTCFullYear(), start.getUTCMonth() + 1);
    planned.push({ month: monthKey(start), start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10), complete: end.getTime() <= currentMonthStart.getTime() || Boolean(through) });
  }
  return planned;
}

export function fetchAmplifyCosts({ start, end }, runAws = runAwsJson) {
  const rows = [];
  let nextPageToken;
  do {
    const tokenArguments = nextPageToken ? ["--next-page-token", nextPageToken] : [];
    const page = runAws([
      "ce", "get-cost-and-usage", "--region", COST_EXPLORER_REGION,
      "--time-period", `Start=${start},End=${end}`, "--granularity", "MONTHLY",
      "--metrics", "UnblendedCost", "UsageQuantity",
      "--filter", JSON.stringify({ Dimensions: { Key: "SERVICE", Values: [AMPLIFY_SERVICE_NAME] } }),
      "--group-by", "Type=DIMENSION,Key=USAGE_TYPE", "Type=DIMENSION,Key=LINKED_ACCOUNT",
      ...tokenArguments,
    ]);
    for (const result of page.ResultsByTime ?? []) {
      for (const group of result.Groups ?? []) {
        rows.push({
          month: result.TimePeriod.Start.slice(0, 7),
          usageType: group.Keys[0],
          account: group.Keys[1],
          cost: Number(group.Metrics.UnblendedCost.Amount),
          quantity: Number(group.Metrics.UsageQuantity.Amount),
          unit: group.Metrics.UsageQuantity.Unit,
        });
      }
    }
    nextPageToken = page.NextPageToken;
  } while (nextPageToken);
  return rows;
}

export function collectAppBuildMinutes({ start, end }, runAws = runAwsJson, region) {
  const regionArguments = region ? ["--region", region] : [];
  const startTime = Date.parse(start);
  const endTime = Date.parse(end);
  const minutesByApp = [];
  for (const app of runAws(["amplify", "list-apps", ...regionArguments]).apps ?? []) {
    let minutes = 0;
    let buildCount = 0;
    const branches = runAws(["amplify", "list-branches", "--app-id", app.appId, ...regionArguments]).branches ?? [];
    for (const branch of branches) {
      let nextToken;
      let reachedOlderJobs = false;
      do {
        const tokenArguments = nextToken ? ["--next-token", nextToken] : [];
        const page = runAws(["amplify", "list-jobs", "--app-id", app.appId, "--branch-name", branch.branchName, "--no-paginate", ...tokenArguments, ...regionArguments]);
        for (const job of page.jobSummaries ?? []) {
          const jobStart = Date.parse(job.startTime);
          if (jobStart < startTime) {
            reachedOlderJobs = true;
            continue;
          }
          if (jobStart >= endTime || !job.endTime) continue;
          minutes += Math.ceil((Date.parse(job.endTime) - jobStart) / 1000 / SECONDS_PER_BILLED_MINUTE);
          buildCount += 1;
        }
        nextToken = page.nextToken;
      } while (nextToken && !reachedOlderJobs);
    }
    minutesByApp.push({ appId: app.appId, name: app.name, minutes, buildCount });
  }
  return minutesByApp.sort((left, right) => right.minutes - left.minutes);
}

function median(values) {
  const sorted = [...values].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 1 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

function nearestRankQuantile(values, quantile) {
  const sorted = [...values].sort((left, right) => left - right);
  return sorted[Math.max(0, Math.ceil(quantile * sorted.length) - 1)];
}

export function deriveBudgetThreshold(monthlyCosts, windowSize) {
  if (monthlyCosts.length === 0) throw new Error("no completed months of cost history to derive a budget threshold from");
  const baseline = median(monthlyCosts.slice(-windowSize));
  const growthRatios = [];
  for (let index = 1; index < monthlyCosts.length; index += 1) {
    const priorMedian = median(monthlyCosts.slice(Math.max(0, index - windowSize), index));
    if (priorMedian > 0) growthRatios.push(monthlyCosts[index] / priorMedian);
  }
  const factor = growthRatios.length === 0 ? 1 : Math.max(1, nearestRankQuantile(growthRatios, THRESHOLD_QUANTILE));
  return { baseline, factor, growthRatios, threshold: Math.round(baseline * factor * 100) / 100, monthsUsed: monthlyCosts.length };
}

export function monthlyTotals(rows, plannedMonths) {
  return plannedMonths.map(({ month, complete }) => ({ month, complete, cost: rows.filter((row) => row.month === month).reduce((sum, row) => sum + row.cost, 0) }));
}

export function budgetPlanCommands({ accountId, threshold, region = COST_EXPLORER_REGION }) {
  const budget = { BudgetName: BUDGET_NAME, BudgetType: "COST", TimeUnit: "MONTHLY", BudgetLimit: { Amount: threshold.toFixed(2), Unit: "USD" }, CostFilters: { Service: [AMPLIFY_SERVICE_NAME] } };
  const notifications = [{
    Notification: { NotificationType: "ACTUAL", ComparisonOperator: "GREATER_THAN", Threshold: 100, ThresholdType: "PERCENTAGE" },
    Subscribers: [{ SubscriptionType: "SNS", Address: `arn:aws:sns:${region}:${accountId}:${ALERT_TOPIC_NAME}` }],
  }];
  const topicPolicy = {
    Version: "2012-10-17",
    Statement: [{ Sid: "AllowBudgetsToPublish", Effect: "Allow", Principal: { Service: "budgets.amazonaws.com" }, Action: "SNS:Publish", Resource: `arn:aws:sns:${region}:${accountId}:${ALERT_TOPIC_NAME}`, Condition: { StringEquals: { "aws:SourceAccount": accountId } } }],
  };
  return [
    "# Writes to AWS. Not run by this command; review, then run with AWS_PROFILE=papyrus-production.",
    `aws sns create-topic --region ${region} --name ${ALERT_TOPIC_NAME}`,
    `aws sns set-topic-attributes --region ${region} --topic-arn arn:aws:sns:${region}:${accountId}:${ALERT_TOPIC_NAME} --attribute-name Policy --attribute-value '${JSON.stringify(topicPolicy)}'`,
    `aws sns subscribe --region ${region} --topic-arn arn:aws:sns:${region}:${accountId}:${ALERT_TOPIC_NAME} --protocol email --notification-endpoint "$(aws ssm get-parameter --region ${region} --name ${ALERT_EMAIL_PARAMETER_NAME} --with-decryption --query Parameter.Value --output text)"`,
    `cat > amplify-budget.json <<'JSON'\n${JSON.stringify(budget, null, 2)}\nJSON`,
    `cat > amplify-budget-notifications.json <<'JSON'\n${JSON.stringify(notifications, null, 2)}\nJSON`,
    `aws budgets create-budget --account-id ${accountId} --budget file://amplify-budget.json --notifications-with-subscribers file://amplify-budget-notifications.json`,
    "# Each later month, re-derive and replace the limit:",
    `aws budgets update-budget --account-id ${accountId} --new-budget file://amplify-budget.json`,
    `# Prerequisite: SSM SecureString ${ALERT_EMAIL_PARAMETER_NAME} holds the alert address (created by hand or by IaC, never committed).`,
  ].join("\n");
}

function formatNumber(value, fractionDigits) {
  return value.toLocaleString("en-US", { minimumFractionDigits: fractionDigits, maximumFractionDigits: fractionDigits });
}

export function formatCostReport({ plannedMonths, rows, appMinutesByMonth, derivation }) {
  const out = [];
  out.push(`Amplify cost by month, usage type and account (Cost Explorer, service "${AMPLIFY_SERVICE_NAME}", unblended)`, "");
  out.push(`${"Month".padEnd(9)}${"Account".padEnd(14)}${"Usage type".padEnd(36)}${"Quantity".padStart(14)}  ${"Unit".padEnd(10)}${"Cost USD".padStart(10)}`);
  for (const { month, complete } of plannedMonths) {
    const monthRows = rows.filter((row) => row.month === month).sort((left, right) => right.cost - left.cost);
    for (const row of monthRows) {
      out.push(`${(complete ? month : `${month}*`).padEnd(9)}${row.account.padEnd(14)}${row.usageType.padEnd(36)}${formatNumber(row.quantity, 1).padStart(14)}  ${row.unit.padEnd(10)}${formatNumber(row.cost, 2).padStart(10)}`);
    }
    const monthTotal = monthRows.reduce((sum, row) => sum + row.cost, 0);
    out.push(`${month.padEnd(9)}${"total".padEnd(50)}${" ".repeat(14)}  ${" ".repeat(10)}${formatNumber(monthTotal, 2).padStart(10)}`);
  }
  if (plannedMonths.some(({ complete }) => !complete)) out.push("", "* month to date");
  if (appMinutesByMonth) {
    for (const { month, apps } of appMinutesByMonth) {
      out.push("", `Build minutes per app, ${month} (elapsed job durations rounded up to whole minutes; approximate)`);
      for (const app of apps.filter((entry) => entry.minutes > 0)) out.push(`  ${app.name.padEnd(30)} ${formatNumber(app.minutes, 0).padStart(8)} min  ${String(app.buildCount).padStart(5)} builds`);
    }
  }
  if (derivation) {
    out.push("", `Budget threshold learned from ${derivation.monthsUsed} completed month(s) with spend: baseline ${formatNumber(derivation.baseline, 2)} (median of the trailing window) x factor ${derivation.factor.toFixed(3)} (upper quartile of month-over-month growth ratios, never below 1) = ${formatNumber(derivation.threshold, 2)} USD`);
  }
  return `${out.join("\n")}\n`;
}

export function runAmplifyCostCommand(optionOf, hasFlag, { runAws = runAwsJson, today = new Date() } = {}) {
  const windowSize = Number(optionOf("months", "3"));
  if (!Number.isInteger(windowSize) || windowSize < 1) throw new Error("--months must be a positive whole number");
  const through = optionOf("through");
  if (through !== undefined && !/^\d{4}-(0[1-9]|1[0-2])$/.test(through)) throw new Error("--through must look like 2026-10");
  const plannedMonths = planMonths({ months: windowSize, through, today });
  const rows = fetchAmplifyCosts({ start: plannedMonths[0].start, end: plannedMonths[plannedMonths.length - 1].end }, runAws);
  const appMinutesByMonth = hasFlag("no-apps")
    ? null
    : plannedMonths.map((planned) => ({ month: planned.month, apps: collectAppBuildMinutes(planned, runAws, optionOf("region")) }));
  const completedCosts = monthlyTotals(rows, plannedMonths).filter((entry) => entry.complete && entry.cost > 0).map((entry) => entry.cost);
  const derivation = completedCosts.length > 0 ? deriveBudgetThreshold(completedCosts, windowSize) : null;
  process.stdout.write(formatCostReport({ plannedMonths, rows, appMinutesByMonth, derivation }));
  if (hasFlag("plan-budget")) {
    if (!derivation) throw new Error("--plan-budget needs at least one completed month; use --through to anchor on one");
    const accountId = runAws(["sts", "get-caller-identity"]).Account;
    process.stdout.write(`\n${budgetPlanCommands({ accountId, threshold: derivation.threshold })}\n`);
  }
}
