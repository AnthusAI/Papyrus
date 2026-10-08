# p.apyr.us: backend feature cutover handoff

The new p.apyr.us site gets a fresh backend built from the packages (PPY-d1cc15).
The old backend (Amplify app `dbsyytcm9drqa`, branch `main`) stays untouched until
cutover. Inbound email and storage backups are kept; Slack and the console
responder are dropped (Ryan, 2026-10-07).

Feature flags for the new app (`cms.environment` in the site config): inbound email
`false` until cutover, storage backups `true`, Slack `false`, console responder `false`.
Every account-global name the new backend creates is brand-scoped, so it deploys
beside the old one; the table is in `docs/site-hosting.md`, "Backend features and
account-global names".

## SES handoff order (inbound mail for p.apyr.us)

1. Deploy the new backend with `PAPYRUS_ENABLE_INBOUND_EMAIL=true` before cutover day
   (the receipt rule set it creates is inactive; the old set stays active and keeps
   receiving mail).
2. Review the new set: `aws ses describe-receipt-rule-set --rule-set-name papyrus-site-inbound-<brand> --region us-east-1`
   (`<brand>` is `defaultBrand` in `papyrus.config.ts`, for example `p-apyr-us`).
3. At cutover: `aws ses set-active-receipt-rule-set --rule-set-name papyrus-site-inbound-<brand> --region us-east-1`.
   This replaces the old active set in one call; no CloudFormation delete is involved.
4. Send a test mail to `submissions@p.apyr.us` and confirm the object lands in the
   new media bucket under `inbound-email/`.
5. Rollback: `aws ses set-active-receipt-rule-set --rule-set-name papyrus-inbound-p-apyr-us --region us-east-1`.
6. Retire (after the rollback window): delete the old stack only after the new set is
   active; the old stack's activation resource deactivates the active set when it is
   deleted, so re-activate the new set immediately afterwards if that ever runs.

The domain identity `p.apyr.us` and the MX record are shared and are not touched.
