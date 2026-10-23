# p.apyr.us: backend and SES receiving cutover

The current p.apyr.us site, its AppSync backend and the shared Monitoring router
run in `papyrus-production` (`712236451410`, `us-east-1`). The old Amplify app
`dbsyytcm9drqa` and its SES receiver are in `legacy` (`335163751677`). The old
backend remains intact through cutover; do not delete it as part of the first email
test.

## SES inventory and corrected ownership

The old stack `amplify-dbsyytcm9drqa-main-branch-cb38ada667-storage0EC3F24A-1CP824J3CJ16B`
created the receipt set `papyrus-inbound-p-apyr-us` and its
`submissions@p.apyr.us` / `suggestions@p.apyr.us` rule on 2026-05-30. Its S3 action
stores raw mail in the old Amplify bucket. The legacy `p.apyr.us` SES identity
currently reports `Failed`; the production account has no `p.apyr.us` identity and
no receipt set. The CloudTrail event is no longer available, and there is no retained
trail or event data store in the legacy account, so the AWS deployment actor is
unknown. Repository history shows the original feature was wired to the old app's
production main pipeline; that is the code path that explains the legacy ownership.

The prior runbook's statements that one SES set is active globally per region and
that the old identity can simply be reused from another account are incorrect. The
active-set limit is per account and region, identities are account-owned, and SES
processes matching receipt rules independently in multiple accounts for a common
domain. A production rule must be verified in the production account. If both the
legacy and production rules match, one message may be stored twice.

Both known `apyr.us` Route 53 hosted zones currently have
`10 inbound-smtp.us-east-1.amazonaws.com`, but they have different assigned
name-server sets. Public authoritative delegation has not been confirmed. The MX
record currently points to SES and should not be changed for the initial test.

## Controlled production setup

These are preparation steps only. No AWS resources, DNS, IAM grants, rule state or
email have been changed while preparing this runbook.

1. Confirm which hosted zone is publicly delegated for `apyr.us`. Publish the
   production account's SES verification TXT values in that zone and wait for
   `p.apyr.us` verification to succeed in `papyrus-production`. Keep the legacy
   identity and DNS values intact through the rollback window.
2. Create one retained, inactive `papyrus-email-receiving` set in
   `papyrus-production` using `infra/email/papyrus-email-receiving-set.yaml`.
   Attach the disabled `p.apyr.us` publication rule with
   `infra/email/papyrus-email-submissions.yaml`, targeting the existing production
   Monitoring table and router. The receiver remains same-account; it has no
   cross-account S3, Lambda, AppSync or Cyclotron grants.
3. Configure exact recipient aliases and an exact permitted sender in private
   `CONFIG#email`; configure direct publication routing in `CONFIG#router` with
   the p.apyr.us AppSync endpoint. Keep ingestion disabled and the router in dry-run
   until configuration, run permissions and the existing site section sweep are
   verified. No shared-Cyclotron grant is needed for this publication-specific test.
4. At the approved test cutover, activate the production receipt set and disable
   the matching legacy SES rule in account `335163751677` before sending. This
   prevents duplicate intake across accounts. Keep the old set, stack, bucket and
   archived mail available for rollback.
5. Send one authorized test message to the configured publication address. Verify
   the private receipt, one pending canonical Reference, direct publication routing,
   section predictions, and failure/DLQ visibility. Do not accept/reject or publish
   the reference during this test.
6. Rollback, if needed, by disabling the production rule and restoring the legacy
   rule. Do not delete either stack or change MX as part of the test.

The exact sender address and public authoritative DNS zone are still required before
the live test can be activated. Other publication/shared-Cyclotron destinations are
separate configuration and are not part of this first test.
