# Inbound Email Submissions

Papyrus accepts reference suggestions by email at configured addresses on the
publication domain. Messages are stored as `Message` records with
`messageKind = email_submission`, then processed by the
`submissions.email.process` Tactus procedure, which runs the reference
**create**, **find**, and **process** pipeline for direct citations only.

## Addresses

Default deployment configuration:

- `submissions@p.apyr.us` — canonical intake address
- `suggestions@p.apyr.us` — alias used for early testing

Override with:

- `PAPYRUS_INBOUND_EMAIL_DOMAIN`
- `PAPYRUS_INBOUND_EMAIL_LOCAL_PARTS` (comma-separated)

## Authorization

**Sender guard:** the sender address must match a registered `UserIdentity.email`
or `UserProfile.email`. This is a lightweight guard, not cryptographic proof of
identity.

**AppSync access:** `papyrus-ses-inbound-receive` and
`papyrus-email-submission-processor` call GraphQL with **IAM only**.
They are granted access via `allow.resource(...)` on the data schema and
`appsync:GraphQL` on their execution roles. The CLI uses IAM too, with the authoring role.

## Submission contract

Authorized email must include at least one intake signal:

- `https://…` URL or `10.xxxx/...` DOI in the body, **or**
- A single PDF attachment (identifiers extracted from the file), **or**
- A reply in an existing submission feedback thread (see table below)

Open-ended research requests (for example, “research the topic of …” with no
citations or attachments) are rejected.

## Infrastructure

Amplify provisions:

1. SES receipt rules storing raw MIME under `inbound-email/` in the media bucket (S3 action only)
2. EventBridge `Object Created` events on that prefix invoke `papyrus-ses-inbound-receive`, which creates the `Message`
3. `papyrus-email-submission-processor` Lambda — runs create/find/process (scoped to
   references registered from that email, not the full corpus table)
4. A scheduled retry sweep (every 15 minutes) re-invokes intake for MIME objects still under `inbound-email/`

Raw MIME is **retained until processing completes successfully**. On success the processor moves the object to `inbound-email-archived/` (outside the intake prefix) so it is not retried. Failed or pending intake leaves the MIME in place so the same test email can be replayed without resending.

Intake is **idempotent per S3 object**: the `Message` id is derived from the bucket/key, and re-running intake for the same MIME re-invokes the processor instead of creating duplicates.

Inbound email is enabled automatically only on the legacy production Amplify `main`
pipeline (`AWS_APP_ID=dbsyytcm9drqa`, the `productionAppId` of Papyrus's own config).
A site built from the packages turns it on with `features.inboundEmail` in
`papyrus.config.ts` or `PAPYRUS_ENABLE_INBOUND_EMAIL=true`; the config wins over the
environment. Sandboxes never create SES receipt resources. Disable explicitly with
`PAPYRUS_ENABLE_INBOUND_EMAIL=false`. How a second site coexists with the live rule
set is in [Backend features and account-global names](site-hosting.md#backend-features-and-account-global-names).

## DNS and SES setup

Before mail flows end-to-end:

1. `p.apyr.us` must have an **MX** record pointing at `inbound-smtp.us-east-1.amazonaws.com` (priority 10). The site hostname should use a Route 53 **A alias** to CloudFront (not a CNAME), so MX can coexist with web traffic.
2. The legacy p.apyr.us backend provisions SES domain verification (`_amazonses.p.apyr.us` TXT) and activates its receipt rule set on deploy. A site built from the packages does neither: it creates its own inactive rule set, and a human verifies the domain and activates the rule set once (see the site-hosting guide).
3. Deploy the Amplify backend so the receipt rules are created.

## Procedure seed

Seed the cloud procedure after deploy:

```bash
poetry run papyrus procedures seed-required --apply
```

## Submission feedback email

After intake or processing finishes, Papyrus sends an acknowledgment email to
the submitter (`metadata.senderEmail`) via SES. The message is **multipart**
(HTML plus plain text). The reply includes:

- Overall status (`COMPLETED`, `FAILED`, `REJECTED`)
- Find / summarize pipeline counts
- Per-reference title, subtitle, summary (when generated)
- **Newsroom link** for each reference (`/newsroom/references/{lineageId}` on the public site)
- Source fetch plugin (for example `arxiv`, `acm`, `youtube`)
- PDF located or not for academic papers
- Attachments recorded on the reference (role, filename, media type)

### Public reference URLs

Feedback emails build a public URL per reference, for example:

`https://p.apyr.us/newsroom/references/reference-knowledge-corpus-ai-ml-research-…`

Configure the site base URL in `.papyrus/config.yaml` (see `papyrus-config.example.yaml`):

```yaml
schemaVersion: 1
publicSite:
  baseUrl: https://p.apyr.us
```

Lambda deployments set `PAPYRUS_PUBLIC_SITE_BASE_URL` on the inbound processor
(which overrides the config file when the repo checkout is not present). If
neither is set, the default base URL is `https://p.apyr.us`.

Feedback is idempotent: `metadata.feedbackEmailSentAt` prevents duplicate sends.
Disable with `PAPYRUS_INBOUND_FEEDBACK_EMAIL_ENABLED=false`. Override the From
address with `PAPYRUS_INBOUND_FEEDBACK_FROM_EMAIL`.

Rejected intake (unauthorized sender, no citations, research-assignment wording)
invokes the processor with `sendFeedbackOnly: true` so the submitter still gets
an explanation without running find/process.

The media bucket must have **S3 EventBridge notifications** enabled so
`InboundEmailStack` can run the receive Lambda on `inbound-email/` object creates
(and the 15-minute retry sweep can re-process stuck MIME). CDK enables this when
`PAPYRUS_ENABLE_INBOUND_EMAIL` or storage backups are on.

**Unregistered senders** (`metadata.authorized = false`,
`metadata.rejectionKind = unregistered_sender`) receive a dedicated rejection
receipt explaining that only registered Papyrus users may submit by email, with
a link to sign in. The same address must be registered on your account before
resubmitting.

## Replying to submission feedback

Acknowledgment emails set a stable RFC `Message-ID` of the form
`<message-email-submission-…@p.apyr.us>` so replies can be correlated to the
original submission `Message`.

| Intake shape | Handling |
|--------------|----------|
| **Single URL/DOI, minimal prose** | Deterministic pipeline: create / find / process direct citations |
| **Multiple URLs** (e.g. forwarded newsletter) | **Console agent** — file relevant references, create **insight** Messages where prose discusses a paper (`papyrus.reference.insight_create`), skip footer/nav links. HTML-only forwards extract links from anchor `href` attributes (visible text after tag-stripping often has no URLs). |
| **URL + substantial message** | **Console agent** — decide filing vs editorial insight vs question vs command (knowledge search, list references, etc.) |
| **PDF only** (one attachment, no body URL/DOI) | Deterministic: extract DOI/arXiv from PDF (GROBID header when `BIBLICUS_GROBID_URL` is reachable, else PDF-byte heuristics), attach to existing corpus reference or create from identifier, then find/process |
| **PDF + URL/DOI or multiple PDFs or PDF + long prose** | **Console agent** |
| **Reply: attachments only** (no new prose) | Deterministic PDF filing when parent submission had exactly one reference |
| **Reply: attachments + message**, or filing failed | **Console agent** with parent submission context |
| **No citations, not a reply, no PDF** | Rejected |

Reply-To on feedback mail is `submissions@p.apyr.us`. Intake stores
`metadata.parentSubmissionMessageId`, `metadata.intakeClassification`, and MIME
thread headers on the new inbound `Message`.

## SES sandbox and feedback recipients

Inbound mail to `submissions@p.apyr.us` does **not** require verifying each
sender. **Outbound** feedback replies are subject to SES account mode:

| Account mode | Who can receive feedback |
|--------------|---------------------------|
| **Sandbox** | Only [verified identities](https://docs.aws.amazon.com/ses/latest/dg/verify-addresses-and-domains.html) (individual emails or whole domains) |
| **Production** | Any deliverable address (normal bounce/complaint rules) |

The **From** address uses your verified domain (`submissions@p.apyr.us` on
`p.apyr.us`). Each **To** address (`metadata.senderEmail`) must be verified in
sandbox before SES will deliver the acknowledgment.

### Verify submitter mailboxes (CLI)

Use credentials with `ses:CreateEmailIdentity` and `ses:GetEmailIdentity` (admin
or a role with SES full access). Region must match deployment (`us-east-1`).

```bash
chmod +x scripts/verify-ses-feedback-recipients.sh

# Request verification and show status for each address:
AWS_PROFILE=YourProfile ./scripts/verify-ses-feedback-recipients.sh \
  rap@endymion.com \
  ryan@anth.us
```

Or per address:

```bash
aws sesv2 create-email-identity --email-identity rap@endymion.com --region us-east-1
aws sesv2 get-email-identity --email-identity rap@endymion.com --region us-east-1 \
  --query VerificationStatus
```

### Confirmation email (required)

`create-email-identity` triggers an email from AWS (subject along the lines of
“Amazon Web Services – Email Address Verification Request”). **Someone with access
to that inbox must click the link.** Until `VerificationStatus` is `SUCCESS`,
feedback sends to that address will fail in sandbox.

- Check spam/junk if it does not arrive within a few minutes.
- To resend: delete the identity and create it again, or use the SES console
  **Resend** action on the pending identity.

```bash
aws sesv2 delete-email-identity --email-identity rap@endymion.com --region us-east-1
aws sesv2 create-email-identity --email-identity rap@endymion.com --region us-east-1
```

### Verify a whole domain (optional)

If all submitters share one domain (for example `@anth.us`), verify the **domain**
in SES instead of every mailbox. Add the DNS records SES provides; then any
address on that domain can receive feedback without per-user verification.

### Leave sandbox (recommended for production)

SES console → **Account dashboard** → **Request production access**. Describe
transactional replies to registered users who submitted citations by email.

## Dogfooding checklist

Before relying on email for knowledge-base building:

1. **Deploy** inbound receive, email processor, and console-chat-responder; set
   `PAPYRUS_PUBLIC_SITE_BASE_URL` and `PAPYRUS_INBOUND_EMAIL_CORPUS_KEY`.
2. **SES sandbox:** verify each submitter mailbox (or the whole sender domain) so
   feedback replies deliver — see [SES sandbox](#ses-sandbox-and-feedback-recipients).
3. **PDF-only intake:** set `BIBLICUS_GROBID_URL` on the email processor (or a
   reachable GROBID service in the same VPC) for reliable header metadata; without
   it, DOI/arXiv heuristics on PDF bytes still run but are less complete.
4. **Console agent:** ensure `PAPYRUS_CONSOLE_RESPONSE_TARGET=cloud` and the
   responder can reach Tactus / GraphQL for newsletter, commands, and fallbacks.
5. **Seed procedures:** `poetry run papyrus procedures seed-required --apply`.

Exercise each row in the [reply routing table](#replying-to-submission-feedback)
plus a **PDF-only** first message and a **newsletter forward** with several links.

## Manual test

From a registered user mailbox, send email to `suggestions@p.apyr.us` with a
subject and body that include at least one URL or DOI. Confirm a
`email_submission` message appears in GraphQL and new pending `Reference` rows
are created for the configured corpus (`PAPYRUS_INBOUND_EMAIL_CORPUS_KEY`,
default `AI-ML-research`). You should receive a feedback email at the sender
address when processing completes.

## Replay an archived submission (local, pre-deploy)

Use a production archived MIME key to inspect or re-run find/process with the code
in your checkout (IAM credentials required):

```bash
chmod +x scripts/verify-archived-email-submission.sh
AWS_PROFILE=Ryan ./scripts/verify-archived-email-submission.sh \
  --archive-key 07an4t5f11qb4pd82kv15dv5kh2ufqfnt9vepkg1

# Re-run find + summarize with local fixes (mutates production references):
AWS_PROFILE=Ryan ./scripts/verify-archived-email-submission.sh \
  --archive-key 07an4t5f11qb4pd82kv15dv5kh2ufqfnt9vepkg1 --rerun
```

Example archive key from `rap@endymion.com` batch (2026-06-01): `07an4t5f11qb4pd82kv15dv5kh2ufqfnt9vepkg1`
→ message `message-email-submission-40ca4b073ca02d75f724` (arXiv `2605.23071`).

## Harder testing

### Unit tests (fast, no AWS)

```bash
poetry run python -m unittest procedures.newsroom.tests.test_email_submissions -v
```

Covers citation parsing, S3 key filters, stable message ids, GSI fields on status
updates, MIME archive copy/delete behavior, and scoped GraphQL loads (no full-table
`listReferences` scans during processing).

GitHub Actions workflow `.github/workflows/inbound-email-tests.yml` runs the same
suite on pushes/PRs that touch inbound email code.

### Production smoke script

After deploy, from the repo (with `amplify_outputs.json` or `PAPYRUS_MEDIA_BUCKET_NAME`):

```bash
chmod +x scripts/test-inbound-email-production.sh
AWS_PROFILE=Ryan ./scripts/test-inbound-email-production.sh
```

Optional: re-run the processor for one message (slow; corpus find/process can take minutes):

```bash
MESSAGE_ID=message-email-submission-XXXXXXXX \
  AWS_PROFILE=Ryan ./scripts/test-inbound-email-production.sh
```

**Pass criteria:**

| Check | Expected |
|-------|----------|
| Receive + processor Lambdas | `PAPYRUS_MEDIA_BUCKET_NAME` set |
| `model-attachment-upload` Lambda | `PAPYRUS_MEDIA_BUCKET_NAME` / `papyrusMedia_BUCKET_NAME` set |
| After successful processing | MIME under `inbound-email-archived/`, not under `inbound-email/` (except `AMAZON_SES_SETUP_NOTIFICATION`) |
| Retry sweep | `processedCount: 0` when nothing pending; otherwise `responseStatus: COMPLETED` |

### Replay without resending mail

1. Leave (or restore) a MIME object under `inbound-email/<key>`.
2. Invoke retry sweep:

   ```bash
   aws lambda invoke --function-name <receive-fn> \
     --payload '{"source":"papyrus.inbound-email","action":"retry-pending"}' \
     --cli-binary-format raw-in-base64-out /tmp/out.json
   ```

3. Or invoke the processor directly:

   ```bash
   aws lambda invoke --function-name <processor-fn> \
     --payload '{"messageId":"message-email-submission-..."}' \
     --cli-binary-format raw-in-base64-out /tmp/out.json \
     --cli-read-timeout 600
   ```

### Common failures

| Symptom | Likely cause |
|---------|----------------|
| `Missing Papyrus storage bucket environment variable` | Resolver Lambdas missing `PAPYRUS_MEDIA_BUCKET_NAME` (deploy `backend.ts` media env block) |
| `cannot import name 'run_reference_metadata_generation_from_extracted_text'` | Wrong import in `email_submissions.py` (use `reference_metadata_generation`) |
| `papyrus-semantic-relation-types.yml` not found | Processor bundle missing `corpora/*.yml` |
| `s3:ListBucket` on archive | Processor role needs bucket-level `ListBucket` (not only object ARNs) |
| Deploy `CloudformationStackCircularDependencyError` | GraphQL Lambdas must use `resourceGroupName: "data"` **inside** `defineFunction({...})`; avoid `allow.resource()` on storage for data-stack functions |
