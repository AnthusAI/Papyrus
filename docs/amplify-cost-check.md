# Amplify cost check

Amplify bills build minutes. `papyrus-infra cost amplify` answers "what did Amplify cost, and which apps built?" in one command. It only reads.

```bash
AWS_PROFILE=papyrus-production papyrus-infra cost amplify --months 3 --through 2026-10
```

- Cost Explorer, service AWS Amplify, monthly, grouped by `USAGE_TYPE` and `LINKED_ACCOUNT`: quantity (build minutes for `BuildDuration`) and cost.
- Per-app build minutes and build counts for each month, from `aws amplify list-jobs` durations (elapsed time rounded up to whole minutes, so approximate). `--no-apps` skips this.
- Without `--through`, the last month listed is the current month, marked as month to date and left out of the threshold.
- Run it once per account; Cost Explorer shows the account the credentials belong to (or the linked accounts, from the payer account).

## The budget threshold is learned from history

`--plan-budget` derives a monthly threshold from the completed months that had spend, then prints the commands for an AWS Budget. It never runs them.

- Baseline: the median of the trailing window (`--months`, default 3).
- Factor: the upper quartile of month-over-month growth ratios (a month's cost divided by the median of the months before it), never below 1. With one month of history the factor is 1 and the threshold is that month's cost.
- Threshold = baseline times factor. There is no constant. Re-run monthly: the new threshold replaces the old with `aws budgets update-budget` (printed in the plan).
- After the cost-saving changes land, re-baseline by running with `--through` set to the first month that reflects them.

The alert address is read from the SSM SecureString `/papyrus/cost/amplify-alert-email` when the SNS subscription is created. It is never in the repository.

## Monthly check

`.github/workflows/amplify-cost-check.yml` runs on the 2nd of each month and writes the table to the job summary. It does nothing until the repository variable `AMPLIFY_COST_CHECK_ROLE_ARN` names a role that GitHub can assume through OIDC. The role needs only:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": ["ce:GetCostAndUsage"], "Resource": "*" },
    { "Effect": "Allow", "Action": ["amplify:ListApps", "amplify:ListBranches", "amplify:ListJobs"], "Resource": "*" }
  ]
}
```

Create the role with the same OIDC trust pattern as the deploy roles (`infra/amplify-app-shell/`), trusted for this repository only. That is an AWS write: a human reviews it and runs it.
