# Email reference intake

The strict submission receiver (PPY-65026c) accepts newsletters and forwarded links
as untrusted source data. It is separate from the older command-capable inbound
console described in [inbound email submissions](inbound-email-submissions.md).
Deploy and enable it only after reviewing its destination, sender allowlist,
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
access. An exact sender allowlist is additionally required. DMARC, spam and virus
checks must pass, alongside SPF or DKIM. A failed or unavailable check is held
out of reference intake; arbitrary mail forwarding that breaks authentication
may therefore need to be resubmitted by an authorized sender.

Parsing is bounded to 1 MiB, 64 MIME parts, nesting depth 12 and 25 distinct safe
links. Plain text, HTML anchors, transfer encodings and multipart alternatives
are supported. Attachments are not opened. Automated replies and delivery
notifications are rejected; ordinary newsletters are allowed. HTML is parsed as
text and never rendered or executed.

Only public-looking HTTP/HTTPS URLs survive. Credentials, unusual ports, literal
nonpublic IPs, local hosts, unsubscribe/preferences/login/confirmation actions,
tracking redirectors and secret-bearing links are excluded. Tracking parameters
and fragments are removed before deduplication. No URL is fetched, followed or
resolved during intake, including to unwrap a tracker. This bounds intake
network activity to the configured S3 and DynamoDB resources. It intentionally
misses newsletters whose only article links are opaque tracking redirects.
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
  "allowedSenders": ["editor@example.org"],
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

Before storing configuration, validate the two ordinary JSON documents offline
with `validate_email_config(email_config, router_config)` from
`papyrus_content.email_submission_intake`. Allowlist changes belong in private
AWS configuration, not this repository. The receiver uses a consistent read for
each document and pins the routing scope into each discovery; changing an Account,
publication endpoint or shared binding makes old queued discoveries fail closed
until an operator reconciles them.

Within the partition, `EMAIL#<hash>` records `processing`, `queued`, `rejected` or
`failed`, private sender/receipt/MIME provenance and a safe error code. `queued`
means collected, not classified or delivered. `DISC#` and `ROUTE#` rows and
`ROUTERUN#` receipts show routing progress. The existing Monitoring console is
currently tied to its original monitor; inspect these private records and the
receiver's failure queue for this slice. A queued/rejected SES delivery is terminal
and retries return the original outcome. Transient storage/service failures are
raised for bounded Lambda retries and then the DLQ; partial link batches use
conditional discovery writes. Rate limits count each SES delivery once per
sender/hour. Raw MIME and intake receipts expire after 30 days; DLQ messages
expire after 14 days.

## SES ownership and activation

Cloud-backed app shells require explicit baseline email configuration, independent
of the newsletter plugin. Managed mode creates sender resources; existing mode
references an identity and configuration set already owned by a shared or
newsletter stack. Reader-only static sites create no email resources. Existing
sites must adopt the explicit configuration before their next app-shell synth;
reuse the existing SES identity instead of recreating it.

SES identities are regional, and only one receipt rule set is active per account
and region. The submission stack adds a disabled rule to an explicitly selected
existing rule set. It does not activate a set or change DNS. Its dedicated raw
bucket and `email-submissions/` prefix must not feed the legacy console-agent
receiver. Review rule order so the new rule handles submission addresses before
any broader legacy rule.

Production activation, performed separately by the authorized operators:

1. Inventory the region's existing identities, configuration sets and active
   receipt rules; select the owners and reuse shared resources.
2. Review the cloud site's explicit sender configuration and IAM grants. Verify
   DKIM/domain ownership and sending access for editor notifications. Newsletter
   subscription/send features remain optional.
3. Configure the email Monitor and router, allowed senders and Account/publication
   bindings. Keep routing disabled or dry-run while checking configuration.
4. Build the email and updated router artifacts locally, review the CloudFormation
   change sets with the shared Monitoring owner, then deploy only with approval.
5. Review any DNS/MX change separately. Prefer a dedicated receiving subdomain
   when the primary domain already receives mail elsewhere. Receiving Lambda and
   SES must use the same supported receiving region.
6. Enable the exact receipt rule and router after grants and configuration are
   verified. Check private intake outcomes, Monitoring routing status, pending
   References and the site section sweep. The email stack's separate router
   schedule must also be enabled; the older HN/TTAB schedules do not drain an
   email Monitor. Send a real test email only with
   authorization. Inspect DLQ/error alarms and verify retries.

Local artifact build (no upload):

```bash
python infra/monitoring/build.py --email
python infra/monitoring/build.py --router
```

AWS references: [regional identities and receiving](https://docs.aws.amazon.com/ses/latest/dg/regions.html),
[SES Lambda actions](https://docs.aws.amazon.com/ses/latest/dg/receiving-email-action-lambda.html),
and [trusted event fields](https://docs.aws.amazon.com/ses/latest/dg/receiving-email-action-lambda-event.html).
