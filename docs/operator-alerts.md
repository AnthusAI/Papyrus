# Operator alerts: CloudWatch alarms as triage-ready email

PPY-4d1143 (notifications), first slice: PPY-bf63d5, PPY-e92c8e, PPY-dd8c18, PPY-e82423. The plan is `docs/notifications-plan.md` in AnthusAI/Caducus.

Every CloudWatch alarm in papyrus-production (us-east-1) reaches the operator as one email from the `alerts` mailbox of notify.anth.us: what broke, where, the impact, the next step and a link. One message when an incident opens and one when it clears; alarms that fire together share a message. It runs **beside** the existing SNS email, which is unchanged. The code is the `caducus.notify` package; this repository only wires it.

## The path

```
CloudWatch alarm state change -> default bus rule -> papyrus-operator-ingest (+ dead-letter queue)
  -> papyrus-operator-router (incidents, grouping, catalog notes) -> papyrus-operator-email queue (+ dead-letter queue)
  -> papyrus-operator-email -> SES (configuration set papyrus-operators) -> the operator mailbox
papyrus-operator-flush (each minute): clearing messages that are due, group windows that ended
papyrus-operator-reconcile (hourly): opens incidents for alarms already in ALARM
papyrus-operator-heartbeat (every 15 minutes): the same path to the SES mailbox simulator -> Email Delivered on the bus
  -> papyrus-operator-ses-events -> metric Papyrus/Operator HeartbeatDelivered -> alarm papyrus-operator-deadman -> SNS
```

State is in table `papyrus-operator-alerts` (90 day TTL, no point-in-time recovery, no addresses: recipients are pseudonyms keyed by SSM `/papyrus/monitoring/recipient-key`, which the stack creates once and keeps).

## The two last-resort alerts (still SNS)

They must work when the listener does not, so they email through `papyrus-monitoring-alarms` like the old alarms, on ALARM and on OK. The listener ignores every alarm named `papyrus-operator-*`, so they never also arrive as operator mail.

| Alarm | Fires when | What it cannot see |
| --- | --- | --- |
| `papyrus-operator-deadman` | no heartbeat delivery in three 15 minute periods (about 45 minutes): a broken Lambda, queue, IAM change, bad package release, rule, schedule or SES refusal | account suspension, a Region-wide CloudWatch or SNS failure, the mailbox itself |
| `papyrus-operator-ses-at-risk` (composite) | account bounce rate >= 5%, complaint rate >= 0.1% (SES's recommended lines; it may pause at 10% and 0.5%), or a heartbeat send refused, bounced or rejected | the same |

When the old SNS email is removed later (PPY-f66e91), exactly these two stay. The newsletter's bounce and complaint alarms keep their SNS pause actions until PPY-819117.

## What deploys, in what order

**Required first on a new AWS account:** a person runs the one-time approver setup (`infra/pipeline/bootstrap.sh --account <12-digit account id> --approver-only`, then `infra/pipeline/create-environment.sh --reviewer <github login>`) so the release has roles to deploy with. After any change to `infra/pipeline/papyrus-stack-pipeline.yaml` the `role-stack-deploy` workflow plans it and the reviewer approves in GitHub; nobody applies it by hand ([why and how](../infra/pipeline/README.md#changing-the-pipeline-roles-merge-then-approve-in-github)).

Nothing is deployed by the pull request, and nobody runs these by hand (PPY-b8cc79). The pull request's `stack-deploy` dry run prints what each stack would change; a person reads that before merging. The release to `main` then builds the zips, deploys the operator sending stack first and `papyrus-monitoring` second, in one run, through GitHub OIDC (`infra/pipeline/README.md`). The run stops without executing if anything would be Removed or Replaced that `infra/pipeline/allowed-changes.json` does not list, or if a stack is in a failed state. Steps 1 to 3 below are what that run does; read them as the description of its work, and as the manual fallback only if the pipeline is unavailable and Ryan says so.

0. **Before anything.** Merge Caducus PR 7 (the handlers this needs), then set `infra/monitoring/caducus-requirement.txt` to the merge commit (or a release tag) and commit that. Until PyPI works the pin is a Git commit; the file's own comments say how to change it.
1. **Build and upload the zip** (the build needs `git` and network for `pip wheel`):
   `python3 infra/monitoring/build.py --operator --upload "$CODE_BUCKET"` prints `CodeKey papyrus-monitoring/operator-<sha256>.zip`. Same pin and catalog give the same hash, so re-running changes nothing.
2. **Stack `papyrus-newsletter-sending-operators`** (identity, DKIM, MAIL FROM, DMARC under notify.anth.us, configuration set `papyrus-operators`, delivery events to the default bus). Command in `infra/newsletter/README.md`; run it with `--no-execute-changeset` first. It must exist before step 3: the functions send as this identity. The release moves on to step 3 straight away; it does not wait for verification. Check with `aws sesv2 get-email-identity --email-identity notify.anth.us --query '[VerifiedForSendingStatus,DkimAttributes.Status,MailFromAttributes.MailFromDomainStatus]' --output text` to read `True SUCCESS SUCCESS` (minutes, up to about 30).
3. **Change set on `papyrus-monitoring`.** It adds 37 resources, 7 parameters and 5 outputs and changes **none** of the existing ones (checked against develop): the collector, the router and the five existing alarms are untouched. Upload the template to `CodeBucket` and use `--template-url` (it is far over the 51,200 byte `--template-body` limit), pass `OperatorCodeKey=<CodeKey from step 1>`, and keep every other parameter at `UsePreviousValue` (never omit `EditorUserPoolArns`). Read it, then execute.
4. **Optional, any time:** write the triage parameter (below) so links open through IAM Identity Center and site names replace app ids.

### What the change set adds (the IAM, in plain words)

| Role | Can do | Cannot do |
| --- | --- | --- |
| `OperatorCoreRole` (router, flush, reconcile) | read and write the one table and its index; consume the ingest queue; send to the email queue; read three SSM parameters by exact name; write its three log groups; `cloudwatch:DescribeAlarms` (no resource-level permission exists) | send email; touch any other table, queue or parameter |
| `OperatorEmailRole` | the table; consume the email queue; read the same three parameters; `ses:SendEmail` only on the notify.anth.us identity and the `papyrus-operators` set and only with the From address "alerts" at notify.anth.us; `ses:GetAccount` (reads the send rate; no resource-level permission); `cloudwatch:PutMetricData` limited to namespace `Papyrus/Operator` | send as anyone else |
| `OperatorSesEventsRole` | `cloudwatch:PutMetricData` limited to `Papyrus/Operator`; its log group | read the table, SSM or SES |
| `OperatorScheduleRole` | invoke the flush and reconcile functions; send to the ingest queue and the existing schedule dead-letter queue | anything else; it trusts only the Scheduler service in this account |
| `OperatorRecipientKeyRole` | `ssm:PutParameter` on `/papyrus/monitoring/recipient-key` only (create-only, never overwrites) | anything else |

No KMS grants (SecureString parameters use the AWS-managed key; the table uses the AWS-managed key too). Only three grants name no resource, listed above, and a test fails if a fourth appears.

## What happens at first deploy

- **The alarms already in ALARM** (seven on 2026-11-04) do not send on their own: a state change is what sends. The hourly reconcile opens them, grouped by site, so expect those emails within the hour of the first run, including the Amplify site alarms that nobody has ever heard (that is the point). To get them now: `aws lambda invoke --function-name papyrus-operator-reconcile /dev/stdout`. Because the event id comes from each alarm's last state change, a later live event for the same change is a duplicate and does not send twice.
- The five existing monitoring alarms keep sending their SNS email as before.
- The heartbeat starts at once. The dead-man alarm treats missing data as breaching, so a brand-new alarm would fire at once; the stack writes one `HeartbeatDelivered` datapoint when it is first created (`OperatorDeadmanSeed`), so the alarm stays quiet for its first 30 to 45 minutes. If the heartbeat never starts, the alarm fires about 30 to 45 minutes after the deploy. That is the check working.

## Triage notes and links

`infra/monitoring/alarm-catalog.yaml` is Papyrus's catalog: the nine reviewed patterns, the Amplify site alarms (`DeployRenderDrift`, `InvalidatedPaths`, the login broker's `StartCeiling` and `Throttled`), the email intake alarm and the Prospectus broker alarms. An alarm with no entry still sends, labelled "No triage notes yet". To add one: add an entry (first match wins, so specific patterns go first; `(?P<site>...)` names the site), run `python3 -m pytest procedures/newsroom/tests/test_operator_alerts.py`, merge it; the release rebuilds the zip and its change set changes only `OperatorCodeKey`.

Alarm links and site names come from the optional SSM parameter `/papyrus/monitoring/triage`, never from Git:

```json
{"portalUrl": "https://<portal>.awsapps.com/start", "roleName": "<permission set>", "accounts": {"<account id>": "papyrus-production"}, "sites": {"<amplify app id>": "shipped"}}
```

With no parameter (today) or no `portalUrl`, the link goes to the plain CloudWatch console page of the alarm. With a `portalUrl`, it opens through IAM Identity Center with `roleName`, defaulting to the stack parameter `TriageRoleName` (`AdministratorAccess`, the role this account's profile uses). Change that default to a read-only permission set when there is one; it is configuration, not code. Write the parameter as a SecureString by hand (it holds a portal address and account ids).

## Testing with a real email

After the deploy, with no impact on anything else: the dedicated alarm `papyrus-notify-test-alarm` has no actions, no data and no dependents.

```bash
export AWS_PROFILE=papyrus-production
python3 infra/monitoring/operator_test_alarm.py status
python3 infra/monitoring/operator_test_alarm.py raise    # one [ALARM] email within about two minutes
python3 infra/monitoring/operator_test_alarm.py clear    # one [CLEARED] email after its 60 second hold-down
```

The same by hand: `aws cloudwatch set-alarm-state --alarm-name papyrus-notify-test-alarm --state-value ALARM --state-reason test`, then `--state-value OK`. The command touches only that alarm and refuses any other account. To prove the dead-man: add `"OperatorHeartbeatState": "DISABLED"` to the `papyrus-monitoring` entry's `parameters` in `infra/pipeline/stacks.json` and release (every other parameter keeps its previous value); about 45 minutes later `papyrus-operator-deadman` emails by SNS; remove the line, release again, and the OK email follows.

## Operating it

- **Dead-letter queues.** `papyrus-operator-ingest-dlq` and `papyrus-operator-email-dlq` hold what failed five times for 14 days. Read the function's log group (`/aws/lambda/papyrus-operator-*`), fix the cause, then redrive: `aws sqs start-message-move-task --source-arn <dlq arn>`. Nothing alarms on these queues in this slice (dead-letter alarms are M2), so check them after any failure the dead-man reports.
- **A message looks wrong or is missing.** Find the incident or delivery in table `papyrus-operator-alerts` (`INCIDENT#...`, `EVENT#...` rows). Addresses are never logged or stored.
- **Pin to PyPI later.** Replace the single requirement line in `infra/monitoring/caducus-requirement.txt` with `caducus==X.Y.Z`. Nothing else changes.
- **Deleted site stacks.** An Amplify alarm whose stack was deleted stops existing; add a line here if one is left behind.
- **Prospectus.** `prospectus-cli-broker-*` alarms now reach the operator; tell the Prospectus session.

## What this slice does not do

- Alarms in other Regions: the rule is on this Region's default bus.
- Muting an alarm or acknowledging from the email (a Lambda function URL): that is M2 and is not built.
- Clearing an incident whose OK event was lost: reconcile only opens incidents. The clearing event comes from the bus.
- Updating the delivery log from SES events (delivered, bounced): the SES-events function only counts heartbeats until kanbus-06de58.
- Branded or site mail, preferences, Slack, Discord: later milestones.
- No outside watcher: account suspension, a Region-wide CloudWatch or SNS failure and the mailbox stay unwatched.
