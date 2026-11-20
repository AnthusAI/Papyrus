# Cloud email and submission receipts

Email is a cloud-site capability, independent of the newsletter plugin. The app-shell
`email` setting is required whenever `cms` is present. A reader-only static site omits
both `cms` and `email` and creates no email resources. See
[email reference intake](../../docs/email-reference-intake.md) for the runtime contract.

For a new identity, set an explicit domain in the site's `infra/site.json`:

```json
"email": {
  "mode": "managed",
  "sendingDomain": "mail.example.test",
  "senderLocalPart": "notifications"
}
```

This creates an SES identity, configuration set `papyrus-<siteId>` and SNS delivery-event
topic `papyrus-newsletter-events-<siteId>`, with no open/click tracking. The historical topic
name stays compatible with the optional newsletter consumer; it also serves ordinary
notification events. It outputs the DKIM CNAME
names and values; it creates no DNS records, receiving rules, credentials, or sending
permission. Editor notification workers can later be granted access to the specific identity
and configuration set. Staging receives no default sending environment. A custom MAIL FROM
domain and domain DMARC policy remain separately reviewed DNS work.

If a newsletter stack or shared email stack already owns the sending setup, keep that
ownership and declare it explicitly:

```json
"email": {
  "mode": "existing",
  "sendingDomain": "mail.example.test",
  "configurationSet": "existing-site-email",
  "eventTopicName": "existing-site-email-events"
}
```

Existing mode emits settings and outputs without recreating identities, configuration sets,
or topics. Verify those resources exist in the app-shell account and region before activation.
Managed identities, configuration sets and topics have Retain policies; deletion is a separate
operator decision. Moving ownership between stacks requires a reviewed import/migration, never
creating a second owner for the same domain.

The existing `infra/newsletter/papyrus-newsletter-sending.yaml` remains supported for its
current stacks. Do not redeploy a second copy. A newsletter plugin on a newly managed site
must use the same `sendingDomain`, `configurationSet` and `eventTopicName` values. The
default configuration set and topic names match the existing plugin, so enabling newsletters
later does not require another identity or sending stack. Explicit overrides must match on both sides.

The example site files use conspicuous `mail.example.test` existing-resource placeholders.
Replace them with verified owned resources; no live site configuration was migrated here.
Cloud site configurations without `email` now fail validation with a migration explanation.

## Optional receiving stack

`papyrus-email-submissions.yaml` creates one receiver per explicitly scoped Monitoring
destination. A shared destination can serve several publication bindings in one Account;
it does not create parent/child publication ownership. Use the same region as the existing
SES receiving endpoint and Monitoring table. Lambda and raw-mail S3 storage are created there.
Confirm that the region supports SES receiving in the
[current SES endpoints list](https://docs.aws.amazon.com/general/latest/gr/ses.html).

The receiver imports `ExistingReceiptRuleSetName`, stores MIME under `email-submissions/`,
then invokes the Python worker directly with the trusted SES event, then stops rule-set
evaluation. It does not use raw-message headers or a bucket event as authentication authority.
It never activates a rule set, verifies a domain, or changes MX. If the receiving account has
no rule set to own, `papyrus-email-receiving-set.yaml` creates one inactive, retained set for
that account and region. Create it once; all scoped receivers in that account/region add their
own exact-recipient rules to it. SES permits one active set per account/region, while distinct
SES accounts can each process matching rules for the same domain. Moving a destination between
accounts therefore requires disabling the old account's matching rule after the new route is
ready, or the same email may be stored and processed twice. Verify the domain identity separately
in each receiving account. Check active sets and rule ordering before preparing a change set; the
strict rule must precede any broader legacy console-agent rule that could consume these addresses.

### p.apyr.us account correction (read-only inventory, 2026-10-23)

The current site and its Monitoring router are in `papyrus-production` (`712236451410`,
`us-east-1`). The SES receiver left behind is in `legacy` (`335163751677`): CloudFormation
identifies its owner as `amplify-dbsyytcm9drqa-main-branch-cb38ada667-storage0EC3F24A-1CP824J3CJ16B`.
That stack created `papyrus-inbound-p-apyr-us` and its `submissions@`/`suggestions@` rule on
2026-05-30. The legacy `p.apyr.us` identity now reports `Failed`; production has no `p.apyr.us`
identity and no receiving rule set. The legacy receipt rule stores MIME in the old Amplify media
bucket; it has no configured S3 event notification. This is historical state, not the target
ownership for the current site.

CloudTrail has no retained event for the May creation: event history returns no matching event,
and the legacy account reports no trail or event data store. The repository commit that introduced
the feature and CloudFormation's resource timestamps prove the code path and stack ownership, but
do not identify who ran that deployment.

Both known `apyr.us` Route 53 zones currently list the same SES MX record, but their assigned
name-server sets differ. Public authoritative delegation could not be confirmed, and the domain
is not registered in the management or legacy Route 53 Domains accounts. The active zone for
publishing SES verification records is therefore still unknown. Do not copy the old account's
verification status or token into production.

The safe production shape is one retained receipt set in `712236451410`, the scoped receiver
stack attached to that set, and the existing `papyrus-monitoring` router in the same account.
Keep its receipt rule and router sweep disabled while reviewing `CONFIG#email` and `CONFIG#router`.
At an approved cutover, activate the production set and disable the legacy rule for the same
addresses; keep the old bucket and messages for rollback. Do not delete the old rule set, MX
record, DNS, identity or bucket as part of that cutover.

Build the receiver artifact with `python infra/monitoring/build.py --email`; the template's
`CodeBucket` and `CodeKey` refer to that content-addressed artifact. Raw messages expire after
30 days; failures stay in the encrypted dead-letter queue for 14 days. Retention, access and
any longer original-message archive need an explicit operator decision before activation.

Deployment remains an operator action after a reviewed CloudFormation change set. Receipt
`Enabled` and routing `RouterEnabled` both default to `false`. Populate and validate
`CONFIG#email` and `CONFIG#router` in the chosen monitor partition first. `Recipients` must
be the same exact addresses as the configured aliases; sender allowlists belong in private
configuration, never source control. Supply the existing `RouterFunctionArn` with its
separately approved publication/Cyclotron grants. Its five-minute schedule is scoped to
this monitor. Enable only the desired components after testing fixture processing.

Inspect the failure queue/alarm and private Monitoring receipts for errors. The receiver has
only raw-object reads and writes to its monitor partition, with no email sending, agent
invocation, AppSync, or Cyclotron permissions. Its function reserves concurrency 1 by
default; set `ReservedConcurrency=0` where the account quota cannot reserve any.
The durable per-monitor lease still serializes intake. Verify the current quota
before deployment; Monitoring's runbook documents this constraint in production.
The function has two
asynchronous retries; the durable monitor receipt and discovery IDs make retries safe.

No production resources, DNS, security policies or email were changed while implementing
this code. These activation steps remain separate from merging or publishing the engine.

## DMARC for the sending domains and its report mailbox (PPY-6bcae9)

`papyrus-dmarc.yaml` publishes the `_dmarc.<domain>` TXT record of one sending domain: `v=DMARC1; p=none; adkim=r; aspf=r; rua=mailto:<report address>`. The release deploys it as one
stack for each sending domain from `infra/pipeline/stacks.json`: `papyrus-dmarc-anth-us` for `anth.us` and `papyrus-dmarc-mail-machines-on-machines` for
`mail.machines-on-machines.anth.us`, both looking up the `anth.us` zone. Specs: `features_backend/references/dmarc-report-record.feature`.

- **The report address is a deployment parameter, never in Git.** The stack's `ReportAddress` parameter is an `AWS::SSM::Parameter::Value<String>` whose value in `stacks.json` is the
  parameter's NAME, `/papyrus/dmarc/report-address`. CloudFormation reads the address at deploy time (the deploy role already resolves parameters under `/papyrus/`). The mailbox is an
  existing one on the `anth.us` domain. Specs and fixtures use the placeholder `dmarc-reports@example.test`.
- **No external-destination record.** The mailbox is on the same organisational domain as both sending domains (RFC 7489 section 7.1). A mailbox on another domain needs a TXT record
  `<sending domain>._report._dmarc.<that domain>` in that domain's zone, which is a change to this template.
- **The policy starts at `none`** (report only). Moving to `quarantine`, then `reject`, is its own reviewed change to the `DmarcPolicy` value in `stacks.json`, made when the reports show SPF
  and DKIM aligned for every legitimate sender.
- **What this does not cover.** `notify.anth.us` already publishes its own `_dmarc` record from the `papyrus-newsletter-sending-operators` stack, with no report address; that record
  overrides the `anth.us` one for its mail, so its reports need that stack's record changed (a separate, reviewed change, because the record changes owner or gains a parameter).
  The account `ses` stack's DMARC record has no report address either.

What remains before a record exists, in order (nothing here is deployed yet):

1. A person approves the `role-stack-deploy` run that applied `papyrus-dmarc-*` to the pipeline roles (merged in the change before the stacks). A pull request that names a stack the deployed
   roles do not know fails its dry run until then, so the stacks were a second change.
2. A person creates the String parameter `/papyrus/dmarc/report-address` once in `papyrus-production`; it holds the mailbox address. Without it the stacks fail at their change set and nothing is half-made.
3. The release deploys the two stacks.
4. A first aggregate report arrives and is read; a stricter policy is then proposed as its own change.
