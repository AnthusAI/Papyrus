# Email reference intake

The strict submission receiver (PPY-65026c) accepts newsletters and forwarded links
as untrusted source data. It is separate from the older command-capable inbound
console described in [inbound email submissions](inbound-email-submissions.md).
Its destination and account grants are explicit; sender-authentication verdicts remain
provenance signals. This code change does not itself activate email.

## Routing and classification

Each receiver belongs to one configured Monitor and one Account. Its exact
recipient addresses are aliases of the same scope. A publication destination
uses direct routing to one configured publication. A shared destination uses the
existing shared relevance Cyclotron, with explicit Account, run, binding revision,
invoker role and publication outputs. No parent site or child-site ownership is
introduced. Multiple publications continue to have their own AppSync endpoints
and verified canonical corpora; this adapter does not open cross-tenant Knowledge
model access.

The automatic sequence is SES receipt, private MIME storage, deterministic link
extraction, and durable Monitoring records. Authentication-warning messages do
not create discoveries or enter publication routing. An editor can read the
inert message, select candidate article links, and explicitly add them to the
publication's existing pending `Reference` queue. The editor-session action
reuses canonical URL identities without resetting existing curation and records
the editor and email-receipt provenance. Import is not a vote, human label,
classification request, or publication. Editors curate the References through
the existing References workflow. A later authorized section sweep can process
pending references; the email receiver does not start that sweep or create a
scheduler. Its preview is:

The Monitoring action sends a maximum of 20 selected links per API request and
continues through the full selection. This is a work-batch size, not a total
link limit. If a request fails partway through, the editor can retry: canonical
URL intake reuses completed References and preserves existing curation.

```bash
papyrus references decide-site-sections --config <site-steering.yml> --json
```

Applying a sweep requires the site's authorized runtime and explicit doctrine.
Email ingestion and editor import create no human labels, accepted references,
or published items. The receiver sends no acknowledgement and does not execute
console commands.

## Untrusted content and limits

The receiver trusts only an SES-origin invocation, its exact envelope recipients,
and passing spam and virus verdicts. To/Cc, From, Authentication-Results and other
MIME headers cannot grant access or select a destination. SPF, DKIM and DMARC are
recorded as untrusted provenance signals; failed or unavailable results do not
block safe data-only intake. Instead, those messages and their extracted links are
held in [quarantine](#quarantine-accept-or-reject) (`pending_review`), visible only to
editors of the configured destination; they do not create discoveries or reach the
Cyclotron/router until an editor accepts them. A sender address
never grants an editor role or causes a privileged action. Destination publications
come only from the exact recipient's private configuration, and the router checks
that same scope before delivery.

Parsing is bounded to 1 MiB, 64 MIME parts, nesting depth 12 and 2,048 characters
per candidate URL. There is no editorial link-count ceiling: every unique eligible
link in a message accepted under the MIME/byte bounds is retained. Plain text, HTML anchors, transfer encodings and multipart alternatives
are supported. Attachments are not opened. Automated replies and delivery
notifications are rejected; ordinary newsletters are allowed. HTML is parsed as
text and never rendered or executed. A legacy `maxLinks` configuration field is
ignored; it does not truncate or reject message content.

Only public-looking HTTP/HTTPS article URLs become discoveries. Credentials,
unusual ports, literal nonpublic IPs, local hosts, unsubscribe/preferences/login/
confirmation actions and secret-bearing links are excluded. Tracking parameters
and fragments are removed from ordinary article URLs before deduplication. Known
Beehiiv `link.mail.beehiiv.com/ss/c/` wrappers are retained as private unresolved
candidates for editor review, but are not emitted as discoveries or made clickable.
An editor can explicitly resolve a selected article wrapper. The action pins each
connection to validated public DNS answers, preserves hostname verification,
disables ambient proxy/cookie use and automatic redirects, sends HEAD only, and
reads no response body. It bounds redirects and time, rejects private or mixed
DNS answers, action links, unsafe targets and HTTPS downgrades, and returns only a
normalized final article URL. It does not run during intake. Resolving a
recipient-specific article click may reveal a tracking identifier to the sender;
unsubscribe, preference, login, and account-action links are never resolved.
Tests use synthetic DNS and responses only.
Later accession/enrichment remains a separate existing workflow and needs its
own safe-fetch policy; this change does not authorize fetching private resources.

The raw MIME is retained in the private 30-day S3 prefix. Editors can read a safe
text rendering, bounded SES verdicts and every extracted candidate link through the
existing authenticated Monitoring page, scoped to their configured publication.
Authentication-warning submissions are quarantined as `pending_review` and do not create
router discoveries; a held message is read-only until an editor accepts it. Once accepted, the
editor UI renders unresolved tracking URLs as non-clickable text and can explicitly register
selected direct/resolved URLs as pending References.
HTML is converted to inert text: scripts, styles, remote images, markup and active
content are never rendered. Email body text is not sent to the classifier; only
normalized candidate URLs and bounded link titles enter discovery. These private
DynamoDB detail chunks expire with the receipt after 30 days. Operational errors
use codes rather than raw message text or URLs. The broader mailbox reader,
subscription management and deliberate unsubscribe UI remain separate work in
PPY-68d06c.

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
grants. Procedure triggers are prohibited for email
destinations. Editor feedback is not configured; a Cyclotron-decided router always sends it in live mode. No additional inference about site ownership is made.

Email source identity is provenance only. SES's envelope source and the MIME
`From` header are displayed separately and labeled unverified; neither is matched
to Cognito or used to infer who submitted content. Editors who can read the site's
Monitoring page may read only submissions explicitly routed to that publication.
The existing site-pool membership check used by legacy queued receipts remains
for those legacy records; new data-only submissions do not consult Cognito or gain
editor privileges.

Forwarded inline bodies and bounded attached `message/rfc822` parts contribute
links and safe readable text only. Attached message headers never authorize the
submission or alter its destination. Ordinary attachments are ignored. SES spam
and virus verdicts must pass; SPF, DKIM and DMARC results are preserved as signals,
so ordinary forwarding that changes those results can still be reviewed.

Before storing configuration, validate the two ordinary JSON documents offline
with `validate_email_config(email_config, router_config)` from
`papyrus_content.email_submission_intake`. User-pool IDs belong in private
AWS configuration, not this repository. The receiver uses a consistent read for
each document and pins the routing scope into each discovery; changing an Account,
publication endpoint or shared binding makes old queued discoveries fail closed
until an operator reconciles them.

Within the partition, `EMAIL#<hash>` records `processing`, `queued`, `rejected` or
`failed`, private sender/receipt/MIME provenance and a safe error code. Accepted
submissions also write a timestamp-ordered `EMAILINDEX#` row and size-bounded
`EMAILDETAIL#` text/link chunks that expire with the receipt. A compact
JSONL manifest of eligible normalized links is written beside the private MIME in
the same 30-day S3 lifecycle prefix. The receipt records its digest, length, byte
cursor, total link count and processed count. A private one-minute resume schedule
reads pending receipts through the existing `routing` GSI and advances at most 25
links per work batch, with a 60-second processing budget. A message can therefore
span multiple invocations without losing content. Each batch checkpoints its byte
cursor after conditional discovery writes; replay after a crash is idempotent and
does not overwrite discoveries already routed onward. `queued` means every
eligible unique discovery is durable, not classified or delivered. `DISC#` and `ROUTE#` rows and
`ROUTERUN#` receipts show routing progress. The editor-only Monitoring console lists email receipts in the configured
publication newest first, 20 at a time with "Load more" and a "Held for review" filter that always reaches a held message however old, and opens one receipt's inert text and complete extracted link list.
Inspect private receipts and the receiver's failure queue for operational failures. A queued/rejected SES delivery is terminal
and retries return the original outcome. A failed manifest-backed receipt retains
its cursor in the pending index so the resume schedule retries it; failures remain
visible by safe error code. Initial transient failures also use bounded Lambda
retries and then the DLQ. Rate limits count each SES delivery once per
sender/hour. Raw MIME and intake receipts expire after 30 days; DLQ messages
expire after 14 days.

## Quarantine: Accept or Reject

A message the receiver will not route on its own is held in private quarantine rather than
lost or silently accepted. Two kinds of message are held:

- Mail whose SPF, DKIM or DMARC signal did not pass (`pending_review`, with the inert text and
  every extracted link stored for 30 days, as for any accepted message).
- Receipts refused by the earlier authentication gate (`sender_authentication_failed` or
  `sender_not_active_editor`). That gate refused before reading the MIME, so these have no stored
  text, links or verdicts until the operator step below holds them.

Mail that failed SES spam or virus checks, mail for the wrong recipient, and mail that is too
large or cannot be parsed stays refused. It is not held for release and no editor can accept it.

An editor or admin of a destination publication opens the held message on the Monitoring page (or
`?receipt=` link) and sees the inert text, each SES verdict (or `UNAVAILABLE`) and the extracted
links as plain text. Two buttons decide it, with an optional "Why?" textarea:

| Button | Meaning | Result |
| --- | --- | --- |
| Accept | release | The receiver queues the message exactly as if it had been accepted: one discovery per link, router delivery, and the links become eligible to add as pending References. |
| Reject | discard | The message is closed (`discarded`). Its private record stays until the 30-day expiry; nothing is routed. |

How it works:

1. The editor's click calls `monitoringDecideEmailSubmission`. The function validates the signed-in
   editor or admin session (the same check as Reference import), that the site is a configured
   publication, and that the receipt is routed to it. It then writes one `EMAILACTION#<hash>` row
   with a conditional create, so the first decision wins: a double click or retry reports the
   existing decision (`already: true`); the opposite decision is refused as `already_decided`.
   The row records the actor (Cognito sub and, when present, the sign-in email), the time, the
   reason (plain text, up to 500 characters) and a snapshot of the SES verdicts.
2. The receiver's one-minute resume schedule applies pending decisions before it drains the
   queue. It is the only writer of the receipt. Accept builds the manifest from the links the
   editor reviewed and queues the receipt; the existing resume machinery then writes the
   discoveries. Reject sets `discarded`. A busy lease or dependency failure leaves the decision
   pending and retried; a changed destination binding or missing details marks the decision failed
   with a safe code that the page shows (`decision_failed`).
3. The Monitoring page shows the exact state: held, accepted and being queued, accepted, rejected,
   expired, or decision could not be applied. Expired messages can no longer be accepted.

Nothing about the message grants any of this. The envelope sender, the MIME `From`, an editor's
address in the message, and SPF/DKIM/DMARC results never create a role, pick a publication, or
decide a message; they are displayed as untrusted provenance only. Links in a held, rejected or
expired message are inert text; resolving a redirect or adding References from them is refused.

Accepting is a one-message override. It does not enroll the sender or change how future mail is
treated. The decision itself (Accept or Reject) cannot be changed once recorded. Its reason can: the editor may give the label and the explanation in either order, so the same decision sent again with a different reason rewrites the reason on the `EMAILACTION#` row (plus `reasonEditedAt`), for as long as the receiver has not applied the decision (a row the receiver has written an `outcome` on is never rewritten, and the receipt keeps the reason it was applied with). A repeat with no reason, or the same one, changes nothing, and the opposite decision is still refused.

### Holding the two refused receipts (operator step)

Receipts refused by the earlier gate are held by invoking the receiver once. This reads each
receipt's private MIME through the normal bounded parser, stores its inert text and links, keeps
every existing receipt field, records that the verdicts were never captured, and sets
`pending_review`. It is idempotent and writes nothing for receipts that are not legacy refusals.

```bash
aws lambda invoke --function-name papyrus-email-<monitor-id> --cli-binary-format raw-in-base64-out \
  --payload '{"task":"quarantine-legacy","monitorId":"<monitor-id>"}' /dev/stdout
```

Add `"receiptIds":["EMAIL#<hash>", ...]` to hold only specific receipts. The receiver needs the
`dynamodb:Query` grants in `infra/email/papyrus-email-submissions.yaml` (the partition and the
`EMAIL_ACTION#` index key), so deploy that stack update first.

## Repeated copies of the same email

People forward the same newsletter more than once, and each forward is a separate SES delivery with
its own receipt. The receiver fingerprints every message at intake, stores it as `contentFingerprint`
on the receipt, and writes an `EMAILFP#<fingerprint>#<digest>` membership row beside the
`EMAILINDEX#` row. The fingerprint (version 1, `papyrus_content.email_fingerprint`) is the SHA-256 of:

- the subject, lower-cased (NFKC), with every leading `Re:`/`Fwd:`/`Fw:` removed and whitespace collapsed;
- the sorted set of distinct extracted candidate-link URLs (already canonical: tracking parameters and
  fragments removed);
- only when the message has no links, the whitespace-collapsed plain text with quote markers and
  forward header lines (`From:`, `To:`, `Cc:`, `Date:`, `Sent:`, `Subject:`, "Forwarded message")
  removed.

The body is deliberately not hashed when links exist, because a forward adds headers and comments
around the same newsletter and the link set identifies the content. Different subjects, or any
different link, are different emails and are never grouped.

The Monitoring email list shows one item per fingerprint: "Received N times", the latest date, and an
expandable list of every copy with its date and state. The item stands for the copy that still needs a
decision (otherwise the newest copy). Receipts without a fingerprint appear as single items.

One Accept or Reject on the group applies to every copy:

1. The decision writes one `EMAILGROUP#<fingerprint>` row (conditional create, first decision wins; the
   opposite decision from any copy is refused as `already_decided`).
2. Each copy that is still held and undecided gets its own `EMAILACTION#` row carrying the group's actor,
   time and reason plus `groupFingerprint`, so every receipt records the decision and references the
   group decision. The receiver applies them exactly as for a single message. A copy that was
   already decided keeps its own decision. Retrying a group decision completes any copy an interrupted
   request left undone.
3. A copy that arrives after the group was decided inherits the decision and is never put to the editor
   again. If the group was accepted, the copy is queued: a copy that passes authentication goes through
   normally, and a held copy gets an inherited Accept so its links are queued. If the group was rejected,
   the copy is held only long enough for the inherited Reject to close it, even when authentication passes.
   Nothing is routed.

Link import stays idempotent: a Reference request is keyed by the canonical URL, so importing the same
link from several copies of one email never creates a second Reference.

### Backfilling receipts stored before grouping (operator step)

Receipts received before this feature have no fingerprint and list as single items. Invoke the receiver
once to fingerprint them. It reads the stored inert text and links (no S3 or MIME access), adds only
`contentFingerprint` and the membership row, leaves every other field untouched, and seeds a group
decision from an already-decided copy so later copies inherit it. It is idempotent and needs no new IAM grant.

```bash
aws lambda invoke --function-name papyrus-email-<monitor-id> --cli-binary-format raw-in-base64-out \
  --payload '{"task":"fingerprint-backfill","monitorId":"<monitor-id>"}' /dev/stdout
```

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
3. Configure the email Monitor and router, exact recipient addresses and
   Account/publication bindings. Keep routing disabled or dry-run while checking
   configuration.
4. Build the email and updated router artifacts locally, review the CloudFormation
   change sets with the shared Monitoring owner, then deploy only with approval.
5. Confirm the publicly delegated DNS zone before publishing the production SES
   verification TXT. Two `apyr.us` Route 53 hosted zones are present and have different
   name-server sets. Their MX records both currently point to
   `inbound-smtp.us-east-1.amazonaws.com`; preserve the existing MX unless the
   receiving region changes. SES accounts process matching rules independently, so
   avoid overlapping enabled rules during cutover.
6. Enable the production rule and router only after grants, configuration and the
   site's existing section sweep are verified. Disable only the matching legacy
   rule at the approved cutover to prevent duplicate intake; retain its bucket and
   messages through the rollback window. Then send one test message and verify the
   private readable receipt, per-check signals, extracted links, Monitoring routing,
   pending References, section predictions, DLQ/alarm and retries. A sender
   allowlist is not required; source identity remains untrusted.

Local artifact build (no upload):

```bash
python infra/monitoring/build.py --email
python infra/monitoring/build.py --router
```

AWS references: [regional identities and receiving](https://docs.aws.amazon.com/ses/latest/dg/regions.html),
[SES Lambda actions](https://docs.aws.amazon.com/ses/latest/dg/receiving-email-action-lambda.html),
and [trusted event fields](https://docs.aws.amazon.com/ses/latest/dg/receiving-email-action-lambda-event.html).

## Link search key

The receiver explores unresolved links and falls back to Tavily search. The `papyrus-email-submissions` stack parameter `TavilyKeyParameter`
(default `/papyrus/shared/tavily-api-key`; empty disables search) sets `PAPYRUS_TAVILY_KEY_PARAMETER` on the receiver Lambda and attaches
`SubmissionTavilyKeyPolicy`: `ssm:GetParameter` on that one parameter and `kms:Decrypt` only through SSM. See `docs/link-exploration.md`.
