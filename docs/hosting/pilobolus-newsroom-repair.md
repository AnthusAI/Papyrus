# Pilobolus newsroom hostname repair — 2026-10-15

The existing CMS is reachable at https://newsroom.pilobol.us/. This routing repair
uses the existing production origin, authentication and certificate. It does not
publish the organizer preview or change the public reader.

Tracked by PPY-229754f2-4d7d-47f4-95e0-d37ce9776925.

## Cause and applied configuration

AWS profile `papyrus-production` was verified as account `712236451410`.
The Amplify association for `newsroom.pilobol.us` remains FAILED with a
cross-account association approval requirement. The authoritative production
Route53 zone had an A alias to `d1zetef1pubg1n.cloudfront.net`, which was absent
from the production CloudFront inventory; the hostname did not resolve.

The repair follows the existing p.apyr.us and Threat Intelligence HTTPS-origin
pattern. CloudFormation stack `papyrus-edge-pilobol-us-cms` is CREATE_COMPLETE:

- Distribution `E205M49121L1RG`, domain `d2m5ad13uolvrt.cloudfront.net`, Deployed.
- HTTPS origin `main.d1eiwl0gedkmnj.amplifyapp.com`.
- Existing issued ACM certificate `b3dc039b-973f-437b-9525-f5249e9f88ec`.
- Managed CachingDisabled and AllViewerExceptHostHeader policies; cookies,
  query strings and other viewer headers reach the origin. No authenticated
  page caching. The origin receives its Amplify Host, and a function sets
  `x-forwarded-host` to the fixed newsroom hostname.
- Zone `Z0293089287KCGYF9WP1A`, newsroom A alias updated to the new distribution.
  Route53 change `C07782022BNTVVEN40CNW` reached INSYNC.

No IAM, Cognito, Google configuration, nameservers, apex reader distribution,
application build, content or data changed. The existing Cognito client already
allowed both newsroom root and /newsroom login/logout callbacks with Google.
No provider secrets or user credentials were retrieved.

## Verification

HTTPS newsroom root returned 200. A short browser check confirmed
`data-news-desk-access=signedOut`, a visible LOGIN button, and zero page errors.
Clicking LOGIN used existing client `6haipiqgobpt1cfpd3bs62mo9c`, redirect URI
`https://newsroom.pilobol.us/newsroom`, and reached accounts.google.com with title
“Sign in - Google Accounts”. No credentials were entered, so completed
sign-in, private data reads and signed-in editing are not claimed.

https://pilobol.us/ continued to return 200. Physical iPad/Safari was not tested.
A signed-out screenshot is retained locally in the production worktree at
`.papyrus-runs/domain-repair/newsroom-signed-out.png`.

## Reproduce and roll back

The adjacent frontdoor YAML is the exact applied template. DNS was changed
separately because the existing record was not owned by this new stack. The
adjacent DNS JSON is the applied UPSERT; the rollback JSON preserves the exact
previous A alias. Restoring that old target restores the prior broken state,
not a known working CMS. Prefer a verified replacement target if rolling back.

To restore the recorded prior DNS configuration, use the verified production
profile and `aws route53 change-resource-record-sets` with zone
`Z0293089287KCGYF9WP1A` and the rollback JSON. Wait for INSYNC and verify routing
before disabling or deleting the CMS stack. Do not alter the reader stack.
The failed Amplify association was preserved for separate AWS Support cleanup.
