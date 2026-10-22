# Newsletter

Status: signup capture is Live. Sending infrastructure is Live for Shipped. The `newsletter` plugin with double opt-in subscriptions is Built (PPY-949d68) but not yet enabled on any site. Unsubscribe, preferences, issues, alerts and sending are Not built yet.

## What exists

A site can collect newsletter signups. There are two paths. Both only store the address.

### The signup plugin

The `signup` plugin ([plugins.md](plugins.md)) adds a `SignupEntry` model, one guest operation (`submitSignup`), a web component and a "Signups" panel in the newsroom.

- Enable it in the site's `papyrus.config.ts` with `backend: { plugins: ["signup"] }`. The default form is `newsletter`.
- Put the component on a page: `<papyrus-signup form="newsletter" endpoint="..." identity-pool="..."></papyrus-signup>` with the version 1 signup script from `/_plugins/`. The attributes are described in [plugins.md](plugins.md).
- The function checks the address, applies a honeypot field and a minimum fill time, and counts requests per address and identity. A web ACL rate limit is on by default.
- The entry id is a hash of the form and the lower-cased address, so a repeat signup changes nothing.
- Editors and admins read entries; guests cannot read anything.

### The public form endpoint

The built-in public form endpoint ([public-forms.md](public-forms.md)) accepts a post with form id `newsletter` and an `email`. It creates a `Message` with `messageKind: form_submission` and `messageType: newsletter_signup` (`amplify/functions/public-forms/core.ts`). Only editors and admins can read these Messages.

## Listing signups

- Plugin entries: the Signups panel in the newsroom.
- Public form messages: `papyrus messages list --kind form_submission --form newsletter`. Add `--status all` to include handled ones and `--json` for machine output. `papyrus messages handle` marks one handled. See [public-forms.md](public-forms.md).

Email addresses are personal data. Treat them like subscriber records.

## What does not happen today

- The signup plugin and the public form endpoint above send no email. Only the `newsletter` plugin (below) mails a confirmation.
- There is no unsubscribe link, no preferences page, no issue composer and no sending of issues.

## Not built yet

Initiative PPY-31455f plans sending. Its milestones, with what is built:

- M1 (PPY-08dbd8): Amazon SES per site, double opt-in (built, see below), one-click unsubscribe.
- M2 (PPY-19a098): issues composed, approved by an editor and sent once.
- M3 (PPY-024f96): automation and alerts.
- M4 (PPY-df1d54): hardening.

## Email rendering

`papyrus_content.email_render` (pure Python, no network) turns Markus source into a responsive email: HTML with inline styles plus a plain-text alternative.

- `render_issue(subject=, markus=, theme=, footer=, preheader="", site_url=)` renders a marketing issue. The footer carries the reason sentence, a manage link, an unsubscribe link, the site and the postal address. A blank address raises `PostalAddressMissing`.
- `render_transactional(subject=, markus=, theme=, site_name=, site_url=, preheader="", action_url=None, action_label=None)` renders confirmation-style mail with a bulletproof button and a short footer. No address required.
- `theme_from_config(cfg, site_name)` builds an `EmailTheme` from `accent`, `text`, `background` and optional `surface`, `muted`, `fontFamily`, `logoUrl`.
- Markus runs with raw HTML disabled. Relative links and image sources become absolute against `site_url`; links with other schemes than http, https, mailto and tel are unlinked. A fixed tag-to-style map is inlined. The only `<style>` block holds a narrow-screen media query and a dark-mode override. No scripts, external CSS, web fonts or tracking pixels.
- Everything that is not Markus output (subject, preheader, footer fields) is escaped. The subject is collapsed to one line.
- Keep issues under 100 KB of HTML: Gmail clips at 102 KB. A test renders a long sample to guard the markup overhead.
- Preview: `poetry run python -m papyrus_content.email_render out.html` writes `out.html` and `out.txt` for a sample issue.

## Sending stack

Status: Live for Shipped (PPY-874ad4).

Each site that will send newsletters gets its own CloudFormation stack, `papyrus-newsletter-sending-<siteId>`, from `infra/newsletter/papyrus-newsletter-sending.yaml`. It creates the SES identity for the sending domain with Easy DKIM and a custom MAIL FROM domain, the DNS records for them and for DMARC, a configuration set `papyrus-<siteId>` without open or click tracking, and an SNS topic `papyrus-newsletter-events-<siteId>` that carries delivery events. The stack for Shipped sends from `shipped.anth.us`; its identity, DKIM and MAIL FROM checks all pass.

The stack does not send mail and does not lift the SES sandbox. Parameters, the deploy command, verification checks and teardown are in `infra/newsletter/README.md`.

## The newsletter plugin: double opt-in

Status: Built (PPY-949d68), not yet enabled on a site. This is the foundation: the subscriber store, signup and the confirmation email. It stands apart from the `signup` plugin above, which only stores an address.

### Enabling it

Prerequisites: the sending stack for the site is deployed (identity verified, configuration set `papyrus-<siteId>`), and the AWS account is still in the SES sandbox or has production access. In the sandbox SES delivers only to verified addresses, so a confirmation to an ordinary reader is refused until production access is granted. The signup form still answers "check your inbox" (it never reveals delivery), so check the function's logs for `confirmation_send_failed`.

```ts
backend: {
  plugins: [
    {
      name: "newsletter",
      siteId: "shipped",                                   // the sending stack's SiteId
      siteOrigin: "https://shipped.anth.us",               // confirmation links are built on this origin
      computeRoleArn: "arn:aws:iam::<account>:role/<the CmsComputeRoleArn output>",
      sendingDomain: "shipped.anth.us",
      fromAddress: "newsletter@<sendingDomain>",              // a mailbox name at sendingDomain
      fromName: "Shipped",
      instantAlerts: false,                                // must be true before any alert list may use approval: "none"
      theme: { accent: "#...", text: "#...", background: "#...", fontFamily: "...", logoUrl: "https://..." },
      lists: [
        { id: "weekly", name: "...", description: "...", kind: "roundup",
          schedule: { draft: "cron(0 13 ? * FRI *)", timezone: "America/New_York" }, issueType: "newsletter_issue", archivePath: "/roundup/" },
        { id: "alerts-x", name: "...", description: "...", kind: "alert", rule: { sections: ["..."], tags: ["..."], types: ["..."] }, approval: "admin" },
      ],
      // configurationSet and eventTopicName default to papyrus-<siteId> and papyrus-newsletter-events-<siteId>.
    },
  ],
},
```

Invalid settings stop the synth with a readable message: unknown keys, a `fromAddress` off `sendingDomain`, duplicate or malformed list ids, a bad cron or time zone, a roundup without `archivePath`, and `approval: "none"` without `instantAlerts: true`. `schedule`, `issueType`, `archivePath`, `rule` and `approval` are validated now and used by the roundup and alert stories. An alert list with no `rule` matches every published item (an admin still approves each one).

Enabling it is a backend deploy that adds one stack, `newsletter`: a DynamoDB table (retained), a customer-managed KMS key (rotation on, retained), the SSM SecureString `/papyrus/<siteId>/newsletter-key` (generated once, never overwritten, retained) and the `newsletter` Lambda (Python 3.12, arm64, 512 MB, 30 s). It adds no GraphQL model or operation. It publishes `custom.papyrusPlugins.newsletter` (`contract`, `fromName`, list ids, names, descriptions and kinds, `theme`) and `custom.newsletter.actionsFunction` to `amplify_outputs.json`; the CMS routes read both. The IAM role of the function may use the table and its key, read its one parameter, and send mail from `fromAddress` through the site's identity and configuration set only. Only the CMS compute role may invoke it (a resource policy). The CMS app can also take the function name from `PAPYRUS_NEWSLETTER_FUNCTION`.

The plugin needs the CMS app's `/api/*` routes (`app/api/newsletter/*`). They ship with Papyrus, so `papyrus-app sync` adds them to a site repo. A site without the plugin answers 404 on both.

### Routes and form

- `POST /api/newsletter/subscribe`: JSON `{email, lists, page, website, renderedAt, consent, formId}` (8 KB cap, same-origin `Origin` required; `lists` is an array or a comma string). Answers `202 {"status":"check_email"}` for any valid-looking request, `400 {"status":"invalid_email"}` or `{"status":"invalid_lists"}`. A signed-in reader's `siteSubject` is stored with the profile when present; it is never required or logged.
- `GET /api/newsletter/confirm?t=<token>`: a small themed page with a "Confirm subscription" button. It changes nothing, so link scanners are harmless. `POST` (form field `t`) confirms and answers `303` to `GET /api/newsletter/confirm?done=1&l=<listIds>`, which names the lists. An expired or used link shows a page linking back to the site.
- Web component `/_plugins/papyrus-newsletter@1.js` (written to the site bucket when the plugin is on):

```html
<script src="/_plugins/papyrus-newsletter@1.js" defer></script>
<papyrus-newsletter lists="weekly,alerts-x"
  consent="I agree to get the weekly email and alerts, and can unsubscribe at any time."></papyrus-newsletter>
```

Attributes: `lists` (comma separated list ids), `data-lists` (JSON array of `{id,name,description}` taken from `custom.papyrusPlugins.newsletter.lists`, labels the checkboxes; or set `window.papyrusNewsletter = { lists }` once), `consent` (the sentence shown and stored as evidence), `endpoint` (default `/api/newsletter/subscribe`), `form-id`, `label`, `button`, `success`. One list: no checkbox. Several: unticked checkboxes, at least one required. No inline script or style attribute, so it works under a strict CSP.

### What subscribing does

The answer is `check_email` whatever the site knows about the address. A bot (filled `website` field, or a form submitted within 2 s or after 24 h) is accepted silently and nothing happens. Rate limits: 5 per visitor address per 10 minutes, 3 per subscriber per hour, 300 per site per hour; a limited request is still answered `check_email`, sends nothing and logs a CloudWatch EMF metric (`SubscribeRateLimited`, dimension `Scope`). A suppressed address gets nothing.

- New address: a `pending` profile with the consent evidence (`requestedAt`, `formId`, `pageUrl`, the exact wording the form showed, a keyed hash of the visitor address), `pending` list rows, a fresh nonce, and the confirmation email. Pending profiles expire after 30 days (DynamoDB TTL).
- Pending (or unsubscribed) address: a fresh nonce and list set replace the old ones, the earlier link stops working, and the confirmation is resent.
- Confirmed address asking for a new list: a confirmation for only the new lists. Nothing new: nothing happens.
- Confirming (the POST): the token must be valid, unexpired (72 hours) and carry the profile's current nonce, which is cleared at once, so a link works once. The profile becomes `confirmed` (with `confirmedAt`, the confirming IP and user agent), the list rows become `subscribed` with `gsiList` set, and the response includes a manage token for the later preferences story.

The confirmation email is built by `email_render.render_transactional` (theme from the plugin's `theme`), sent with SESv2 from `"<fromName>" <fromAddress>` with the configuration set and the tags `site` and `kind=confirm`.

### Data model

One DynamoDB table (not a GraphQL model; subscriber data never appears in the content API). Keys `pk`, `sk`; TTL `expiresAt`; GSI `byList` on `gsiList` + `sk` (keys only); on demand; customer-managed KMS key; point-in-time recovery off so erasure is real.

| pk | sk | Holds |
|---|---|---|
| `SUB#<hid>` | `PROFILE` | `email` (normalized), `status` pending / confirmed / unsubscribed, `createdAt`, `updatedAt`, `rev`, `siteSubject?`, `confirmNonce?`, `consent` {`requestedAt`, `formId`, `pageUrl`, `wording`, `requestIpHash`, `confirmedAt`, `confirmIp`, `confirmUserAgent`}, `history` [{`at`, `event`}] capped at 50 |
| `SUB#<hid>` | `LIST#<listId>` | `status` pending / subscribed / unsubscribed, `at`; `gsiList` = list id only while subscribed on a confirmed profile |
| `SUPP#<hid>` | `SUPP` | suppression (`reason`, `at`); checked before every send. Written by a later story. |
| `RATE#<kind>#<key>#<window>` | `RATE` | request counters with TTL |

`hid` = hex(HMAC-SHA256(hashKey, lowercased trimmed address))[:32]. A profile is replaced only if its `rev` is the one that was read, in one transaction with its list rows. `hashKey` and the token key are HKDF-SHA256 derived (salt `papyrus-newsletter`, info `hash` / `token`) from the SSM parameter, which the function reads once per container. Later stories add `ISSUE#`, `ALERT#`, `ROUNDUP#` and `STATE` rows to the same table.

### Tokens

`v1.<base64url(json)>.<base64url(hmac-sha256)>`, the HMAC over `v1.<base64url(json)>` with the token key, compared in constant time. The JSON holds `h` (hid), `p` purpose (`confirm` or `manage`), optionally `l` (list ids), `n` (nonce) and `e` (expiry, epoch seconds). Confirm tokens carry `n` and `e` (72 hours) and are single use. Manage tokens (for the unsubscribe and preferences stories) have no expiry and die with the subscriber record.

### Known gaps

Not built: unsubscribe, preferences, erasure, suppression from SES events, the event topic subscription and bounce alarms, issues, sending, alerts and the newsroom panel (stories b5a699 and later). The `unsubscribed` status is already handled as "start a fresh double opt-in" on a new signup. A form left open more than 24 hours is accepted silently and sends nothing; the reader has to reload and try again.
