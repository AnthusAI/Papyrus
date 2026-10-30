# Public forms: the receiving endpoint

Every site backend (`defineSiteBackend`) deploys one public endpoint that turns form posts into newsroom
**Messages**. It serves the data-defined forms of the standard front end (see "Forms" in
[building-a-papyrus-static-site.md](building-a-papyrus-static-site.md)): contact and error-report forms, calls to
action, and newsletter signups.

## Find the URL

The deployed backend publishes it in `amplify_outputs.json` as **`custom.publicForms.endpoint`** (a Lambda Function
URL, for example `https://<id>.lambda-url.us-east-1.on.aws/`). Read it after the site's next backend deploy:

```bash
jq -r '.custom.publicForms.endpoint' amplify_outputs.json
```

Set it in the site config and rebuild the site:

```yaml
contact:
  endpoint: "https://<id>.lambda-url.us-east-1.on.aws/"   # the contact page and Report-an-error links
newsletter:
  signupEndpoint: "https://<id>.lambda-url.us-east-1.on.aws/?form=newsletter"   # or without ?form= if the client sends form=newsletter
```

The form id travels in the query string (`?form=contact`; the standard form adds it itself) or in a `form` body field.
With neither, the id is `contact`. A newsletter signup form's endpoint is the same URL.

## Request

`POST` with `Content-Type: application/json` and a flat object of string fields, at most 20 fields, 5000 characters
per value, 16 KB in all. The standard form sends `form`, `page`, the form's own fields (`topic`, `name`, `email`,
`message`, ...) and the honeypot field (`website` by default). `email`, when present, must look like an address; a
submission needs an `email` or a `message`; the `newsletter` form needs an `email`.

Answers never reflect input: `200 {"ok":true}` on success, `204` for a preflight, otherwise `{"ok":false,"error":CODE}`
with `400` (invalid), `403` (origin), `405`, `413` (too large), `415` (not JSON), `429` (rate limited, with
`Retry-After`) or `500`/`503` (not stored: the page shows its failure text, never a fake success).

## Security controls

- **Origin allow-list.** Only the site's own origins may post: distribution aliases, the reader domain, the revalidate
  base URL and sign-in redirect hosts (https, never localhost), plus `publicForms.allowedOrigins` in the backend config
  (add `https://www.example.org` there when the site is also served from `www`). The handler answers CORS with exactly
  the matching origin and refuses any other, and a request with no `Origin` header, with `403`.
- **Honeypot.** A filled `website` field (more names via `publicForms.honeypotFields`) answers `200` and stores nothing.
- **Rate limits** (DynamoDB counters with TTL, the address stored only as a hash): 10 posts per address per 10 minutes
  across all forms, 120 per form per hour, 400 for the whole site per hour. Tunable with the Lambda environment
  variables `PAPYRUS_PUBLIC_FORMS_IP_LIMIT`, `_FORM_LIMIT`, `_SITE_LIMIT`.
- **Strict input.** JSON object only, string values only, field-name pattern, control characters stripped, size
  limits above, form ids `[a-z0-9-]{1,40}`.
- **No secrets in the browser; no read path.** The function can only create `Message` rows (`allow.resource(...)
  .to(["mutate"])`), and has no query access. Submissions are `searchVisibility: private`.
- A bot challenge (Turnstile) is not part of this endpoint; it is a follow-up if scripted abuse gets past the limits.

## Where submissions go

Each valid post creates a `Message`: `messageKind: form_submission`, `messageDomain: inbox`, `status: active`, the
readable text in `content`, and `metadata` with `formId`, `topic`, all `fields`, `page`, `origin` and `receivedAt`.
Newsletter signups (`form` = `newsletter`) are the same kind with `messageType: newsletter_signup`; sending the
confirmation email is the newsletter initiative's job. Messages are readable only by the `editor` and `admin` groups
(and signed-in newsroom sessions); the guest and API-key roles have no access. Email addresses are personal data:
treat them like subscriber records.

Editors see them in the newsroom Messages feed under the `form_submission` kind filter.

## Triage from the CLI

```bash
papyrus messages list --kind form_submission                 # open submissions, newest first
papyrus messages list --kind form_submission --status all --form contact --json
papyrus messages handle --message-id form-<id> --note "answered by email"
```

A submission is a message from a person, so "handled" is recorded on that same Message: `messages handle` sets its `status`
to `handled` and keeps `handledAt`, `handledBy` and `handledNote` in its metadata. It writes no second Message (Messages come
only from people). Updating a Message needs operator credentials, because the Message model is append-only for editor
sessions. `list` hides handled submissions unless `--status handled|all`.
