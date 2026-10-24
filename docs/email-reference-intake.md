# Email reference intake

The strict submission receiver (PPY-65026c) accepts newsletters and forwarded links
as untrusted source data. It is separate from the older command-capable inbound
console described in [inbound email submissions](inbound-email-submissions.md).
Deploy and enable it only after reviewing its destination, sender authorization,
account grants, SES rules and DNS. This implementation does not activate email.

## Routing and classification

Each receiver belongs to one configured Monitor and one Account. Its exact
recipient addresses are aliases of the same scope. A publication destination
uses direct routing to one configured publication. A shared destination uses the
existing shared relevance Cyclotron, with explicit Account, run, binding revision,
invoker role and publication outputs. No parent site or child-site ownership is
introduced. Multiple publications continue to have their own AppSync endpoints
and verified canonical corpora; this adapter does not open cross-tenant Knowledge
model access.

The sequence is SES receipt, private MIME storage, deterministic link extraction,
durable Monitoring discoveries, publication routing, and existing pending
Reference intake. Canonical URL matches reuse the existing Reference without
resetting its human curation. Private provenance records identify the email and
destination; machine decisions remain machine decisions.

Pending references join the publication's existing `decide-site-sections` sweep.
The shared classifier selects publications; each publication's internal
classifier suggests sections. The receiver does not start a section sweep or
create a new scheduler. Activation must verify that the site's existing sweep is
configured and running. Its preview is:

```bash
papyrus references decide-site-sections --config <site-steering.yml> --json
```

Applying a sweep requires the site's authorized runtime and explicit doctrine.
Email ingestion creates no human labels, accepted references, or published items.
It sends no acknowledgement and does not execute console commands.

## Untrusted content and limits

The receiver trusts the SES invocation's envelope recipients and scan/authentication
verdicts. To/Cc, From, Authentication-Results and other MIME headers cannot grant
access. The outer sender must also match a current verified editor or admin in the
destination publication. DMARC, spam and virus checks must pass, alongside SPF or
DKIM. A failed or unavailable check is held
out of reference intake; arbitrary mail forwarding that breaks authentication
may therefore need to be resubmitted by an authorized sender.

Parsing is bounded to 1 MiB, 64 MIME parts, nesting depth 12 and 2,048 characters
per candidate URL. There is no editorial link-count ceiling: every unique eligible
link in a message accepted under the MIME/byte bounds is retained. Plain text, HTML anchors, transfer encodings and multipart alternatives
are supported. Attachments are not opened. Automated replies and delivery
notifications are rejected; ordinary newsletters are allowed. HTML is parsed as
text and never rendered or executed. A legacy `maxLinks` configuration field is
ignored; it does not truncate or reject message content.

Only public-looking HTTP/HTTPS URLs survive. Credentials, unusual ports, literal
nonpublic IPs, local hosts, unsubscribe/preferences/login/confirmation actions,
tracking redirectors and secret-bearing links are excluded. Tracking parameters
and fragments are removed before deduplication. No URL is fetched, followed or
resolved during intake, including to unwrap a tracker. This bounds intake
network activity to the configured S3 and DynamoDB resources. It intentionally
misses newsletters whose only article links are opaque tracking redirects.
Known Beehiiv `link.mail.beehiiv.com/ss/c/` click wrappers are excluded without
storing their recipient-specific URL; Papyrus does not resolve them or contact
tracking hosts.
Later accession/enrichment remains a separate existing workflow and needs its
own safe-fetch policy; this change does not authorize fetching private resources.

The original MIME stays private for operator inspection. Operational errors use
codes rather than message text or URLs. The broader mailbox reader, subscription
management and deliberate unsubscribe UI remain separate work in PPY-68d06c.

## Destination configuration and receipts

The existing Monitoring table holds two configuration items in the same partition,
`MONITOR#<monitor-id>`. No hostname, recipient header or sender text selects an
Account or AppSync endpoint. Operator configuration and the deployed IAM grants
must agree. An example publication destination is:

```json
{
  "pk": "MONITOR#email-publication",
  "sk": "CONFIG#email",
  "schemaVersion": 1,
  "enabled": false,
  "accountId": "account-example",
  "kind": "publication",
  "addresses": ["submissions@publication.example"],
  "publicationIds": ["publication"],
  "maxMessagesPerSenderHour": 10
}
```

```json
{
  "pk": "MONITOR#email-publication",
  "sk": "CONFIG#router",
  "accountId": "account-example",
  "mode": "dry-run",
  "enabled": false,
  "decisions": "direct",
  "feedback": false,
  "maxItemsPerRun": 5,
  "publications": [{
    "publicationId": "publication",
    "site": "publication.example",
    "userPoolId": "us-east-1_examplePool",
    "appsyncEndpoint": "https://example.appsync-api.us-east-1.amazonaws.com/graphql"
  }]
}
```

For a shared destination, use `kind: "shared"`, an explicit list of permitted
`publicationIds`, and `decisions: "cyclotron"` with the existing router's
`cyclotron` block (`endpoint`, `accountId`, `runId`, `bindingRevision`, `roleArn`).
The Account IDs must match; router publications must exactly match the explicit
grant list. The shared Cyclotron independently enforces the machine invoker's
grants. Procedure triggers and automated feedback are prohibited for email
destinations. No additional inference about site ownership is made.

The sender is authorized only when the outer SES-authenticated From address exactly
matches a unique, enabled Cognito user with `email_verified=true` and current
membership in that publication's `editor` or `admin` group. This matches the
application's `contentWriteGroups` authorization and its managed role assignments
mirror those roles into Cognito. The receiver checks only the
configured publications' user pools; a shared destination records and routes only
the subset where the sender is an editor. The router repeats this check before
normal delivery, retries, and classifier backfill, so revoked access fails closed.
The receiver and router Lambda roles need read-only `cognito-idp:ListUsers` and
`cognito-idp:AdminListGroupsForUser` on the exact configured pool ARNs. This is
pool-scoped directory read access; it does not grant Cognito writes. Cognito user
directory reads can be eventually consistent, so group revocation propagation is
not a synchronous revocation guarantee.

Papyrus maps Google's `email_verified` claim into Cognito's standard
`email_verified` attribute for Google-federated accounts. Cognito treats mapped
email addresses as unverified unless the provider's verification claim is also
mapped. The mapping is part of the auth stack configuration, and Cognito refreshes
mapped values on a subsequent Google sign-in; do not administratively mark a sender
verified. After an auth deployment adds or repairs this mapping, the user must sign
out and sign back in at the publication newsroom before email intake will recognize
the updated verification state. Cognito's one-time verification-code flow does not
verify an email address that came from a federated provider.

Forwarded inline bodies and bounded attached `message/rfc822` parts contribute
links only. Attached message headers never authorize the submission; SES verdicts
and the outer sender still govern authorization. Ordinary attachments are ignored.
SES DMARC PASS is required (plus spam/virus checks and SPF or DKIM PASS), so
automatic forwarding that breaks DMARC is rejected.

Before storing configuration, validate the two ordinary JSON documents offline
with `validate_email_config(email_config, router_config)` from
`papyrus_content.email_submission_intake`. User-pool IDs belong in private
AWS configuration, not this repository. The receiver uses a consistent read for
each document and pins the routing scope into each discovery; changing an Account,
publication endpoint or shared binding makes old queued discoveries fail closed
until an operator reconciles them.

Within the partition, `EMAIL#<hash>` records `processing`, `queued`, `rejected` or
`failed`, private sender/receipt/MIME provenance and a safe error code. A compact
JSONL manifest of eligible normalized links is written beside the private MIME in
the same 30-day S3 lifecycle prefix. The receipt records its digest, length, byte
cursor, total link count and processed count. A private one-minute resume schedule
reads pending receipts through the existing `routing` GSI and advances at most 25
links per work batch, with a 60-second processing budget. A message can therefore
span multiple invocations without losing content. Each batch checkpoints its byte
cursor after conditional discovery writes; replay after a crash is idempotent and
does not overwrite discoveries already routed onward. `queued` means every
eligible unique discovery is durable, not classified or delivered. `DISC#` and `ROUTE#` rows and
`ROUTERUN#` receipts show routing progress. The existing Monitoring console is
currently tied to its original monitor; inspect these private records and the
receiver's failure queue for this slice. A queued/rejected SES delivery is terminal
and retries return the original outcome. A failed manifest-backed receipt retains
its cursor in the pending index so the resume schedule retries it; failures remain
visible by safe error code. Initial transient failures also use bounded Lambda
retries and then the DLQ. Rate limits count each SES delivery once per
sender/hour. Raw MIME and intake receipts expire after 30 days; DLQ messages
expire after 14 days.

## SES ownership and activation

Cloud-backed app shells require explicit baseline email configuration, independent
of the newsletter plugin. Managed mode creates sender resources; existing mode
references an identity and configuration set already owned by a shared or
newsletter stack. Reader-only static sites create no email resources. Existing
sites must adopt the explicit configuration before their next app-shell synth;
reuse the existing SES identity instead of recreating it.

SES identities are regional and account-owned. Only one receipt rule set is active
per account and region; this limit does not span AWS accounts. SES processes matching
receipt rules independently in every account configured to receive the same domain.
The submission stack adds a disabled rule to an explicitly selected rule set. If the
receiving account has no set, create one with
[`papyrus-email-receiving-set.yaml`](../infra/email/papyrus-email-receiving-set.yaml).
Neither stack activates a set or changes DNS. Verify the domain identity separately
in the receiving account. Its dedicated raw bucket and `email-submissions/` prefix
must not feed the legacy console-agent receiver. Review rule order so the new rule
handles submission addresses before any broader rule in that account.

Production activation, performed separately by the authorized operators:

1. Inventory identities, configuration sets, receipt rules and active rule sets
   in the intended receiving account. For p.apyr.us that is `papyrus-production`
   (`712236451410`, `us-east-1`), where no inbound identity or rule set currently
   exists. The old `p.apyr.us` identity in account `335163751677` reports `Failed`;
   identity status cannot be reused across accounts.
2. Review the cloud site's explicit sender configuration and IAM grants. Verify
   DKIM/domain ownership and sending access for editor notifications. Newsletter
   subscription/send features remain optional.
3. Configure the email Monitor and router, allowed senders and Account/publication
   bindings. Keep routing disabled or dry-run while checking configuration.
4. Build the email and updated router artifacts locally, review the CloudFormation
   change sets with the shared Monitoring owner, then deploy only with approval.
5. Confirm the publicly delegated DNS zone before publishing the production SES
   verification TXT. Two `apyr.us` Route 53 hosted zones are present and have different
   name-server sets. Their MX records both currently point to
   `inbound-smtp.us-east-1.amazonaws.com`; preserve the existing MX unless the
   receiving region changes. SES accounts process matching rules independently, so
   avoid overlapping enabled rules during cutover.
6. Enable the production rule and router only after grants, configuration and the
   site's existing section sweep are verified. Disable the corresponding legacy
   rule at the approved cutover to prevent duplicate intake; retain its bucket and
   messages through the rollback window. Then send one authorized test email and
   verify private receipt outcomes, Monitoring routing, pending References, section
   predictions, DLQ/alarm and retries. The exact test sender must first be added to
   the private sender allowlist. No test message has been sent.

Local artifact build (no upload):

```bash
python infra/monitoring/build.py --email
python infra/monitoring/build.py --router
```

AWS references: [regional identities and receiving](https://docs.aws.amazon.com/ses/latest/dg/regions.html),
[SES Lambda actions](https://docs.aws.amazon.com/ses/latest/dg/receiving-email-action-lambda.html),
and [trusted event fields](https://docs.aws.amazon.com/ses/latest/dg/receiving-email-action-lambda-event.html).
