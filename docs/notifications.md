# Notifications (the `notifications` plugin)

Status: Built, off everywhere (PPY-44721a, PPY-38be08). Nothing is enabled on any site. Architecture: `docs/notifications-plan.md` in AnthusAI/Caducus. There is no central service: [Caducus](https://pypi.org/project/caducus/) (`caducus[notify]`, pinned exactly in `amplify/plugins/notifications/function/requirements.txt`) runs inside each site's own stack, with the site's own table.

## What a site gets

One switch in `papyrus.config.ts`, following [plugins.md](plugins.md):

```ts
backend: {
  plugins: [{
    name: "notifications",
    siteId: "example",                       // the sending stack's SiteId; SES set papyrus-<siteId>
    siteOrigin: "https://news.example.com",
    basePath: "",                            // the site's urls.basePath
    sendingDomain: "example.com",
    fromAddress: "notifications@example.com",
    fromName: "Example News",
    theme: { accent: "#aa3300", text: "#111111", background: "#ffffff" },   // same fields as the newsletter's
    lists: [{ id: "stories", name: "New stories", rule: { sections: ["News"] }, approval: "admin" }],
  }],
}
```

`computeRoleArn` comes from `PAPYRUS_COMPUTE_ROLE_ARN` as for the newsletter. Bad settings stop the synth.

The plugin adds one stack, only where it is listed:

| Resource | Notes |
|---|---|
| Table `papyrus-notifications-<siteId>` | retained, customer-managed KMS key with rotation, TTL `expiresAt`, GSI `byRecipient`, no point-in-time recovery |
| SSM `/papyrus/<siteId>/notifications/recipient-key` | SecureString, created once, never overwritten |
| Functions (Python 3.12, arm64, one bundle with `papyrus_content` and Caducus) | `papyrus-notifications-<siteId>` (router), `-email-`, `-flush-`, `-ses-` |
| Queues | the email queue with a dead letter queue, and a dead letter queue for failed asynchronous router invocations; an alarm on each (no alarm action: the account's operator listener reads every alarm) |
| EventBridge rules (default bus) | every minute for the flush; SES events of the site's configuration set, only for mail Caducus tagged with a delivery id |
| IAM | the router reads the one `getPublishedItem` AppSync field; the email function sends only from the configured address through the site's identity and set; only the CMS compute role may invoke the router (a resource policy); `content-actions` may invoke that one function |

No GraphQL model or operation, so no AppSync realtime. The mail carries the site's own theme (`THEME_JSON`, rendered by `papyrus_content.email_render`, passed to Caducus as its renderer).

## The publish path

`src/papyrus_content/publish_alerts.py` is the only place a publish announces. Beside the newsletter, `announce_published` asynchronously invokes the router (`PAPYRUS_NOTIFICATIONS_FUNCTION`, set on `content-actions` by the plugin) with `{"task": "story-published", "itemId", "lineageId", "publishedItemId", "eventId": "story.published:<lineage>"}`. The same rules as the newsletter's alerts apply: only a real publish (`PublishResult.changed`), after the page is live (a failed projection announces from its retry), never on unpublish, edits, reprojection or bulk imports, a no-op when the plugin is off, and every error is logged and swallowed with short timeouts. Each function is tried even if the other failed.

The router reads the published item, drops it unless some list's rule matches (`sections`, `tags`, `types`, as for the newsletter), and hands Caducus a `story.published` event whose id comes from the lineage. Caducus dedupes on that id in the site's table, so a publish, unpublish and publish again mails once.

## Who gets the mail today

Caducus 0.2.0 has no reader directory, consent record or preferences. It sends `operator`-class kinds to the addresses in an SSM StringList, which an operator puts by hand and which is never in Git:

```
aws ssm put-parameter --name /papyrus/<siteId>/notifications/operators --type StringList --value "<address>"
```

The plugin's kind `story.published` (`src/papyrus_content/notifications/data/notification-kinds.json`) is class `operator`, so those addresses are the whole audience, and `approval` is carried in the settings for when lists have readers. The `/api/notifications/{subscribe,confirm,preferences,unsubscribe,state}` routes exist (same-origin rule, 400 and 303 rather than 403 and 404 because the edge rewrites those, a site without the plugin answers 404, `lib/notifications-api.ts`), but the function answers every reader action `503 unavailable` and stores nothing until a Caducus release adds public audiences. The pages those routes redirect to are projected on the site (next section).

## Reader pages (PPY-f361ee)

A reader subscribes, confirms and manages notifications on real pages of the site, in its own header, theme and footer (light, dark, phone), never on an `/api` address. When `notifications` is in `PAPYRUS_PLUGINS`, the standard projector writes seven pages (`src/papyrus_content/projection/standard/notifications_pages.py`, modelled on the newsletter's pages in [newsletter.md](newsletter.md)):

| Page | Purpose |
|---|---|
| `<base>/notifications/` | Subscribe: the `<papyrus-notifications>` web component |
| `<base>/notifications/confirm/` | Confirm button for the emailed link |
| `<base>/notifications/confirmed/` | Subscribed, with a link to manage |
| `<base>/notifications/preferences/` | Manage: one button per list that is On or Off, Save, Unsubscribe from everything, Delete my data (with a confirm step) |
| `<base>/notifications/unsubscribe/` and `unsubscribed/` | One-click landing page and its result |
| `<base>/notifications/expired/` | A link that is no good; points back to the subscribe page |

They are always the directory form (`notifications/confirm/index.html`) whatever `urls.style` says, because the emails and the `/api/notifications/*` redirects use those exact addresses. They are `noindex`, carry `<meta name="referrer" content="same-origin">` (so form posts send the site's real `Origin`), and have no Markdown twin and no place in any sitemap, `llms.txt`, `llms-full.txt` or feed. A reconcile never deletes pages under `notifications/` unless the verified deployed plugin list lacks `notifications`. A site without the plugin has none of them.

- **Scripts (external, no inline script or style, so a strict CSP is fine).** `/_plugins/papyrus-notifications-pages@1.js` (every page) reads `token`, `list`, `lists`, `msg` and `step`, fills the hidden `t` fields and fetches names and state from `/api/notifications/state`; `/_plugins/papyrus-notifications@1.js` (the subscribe page only) defines `<papyrus-notifications>`, which reads the offered lists with `GET /api/notifications/state?kind=offered` (the site's public list settings, nothing about any reader) and posts to `/api/notifications/subscribe`. Attributes: `lists`, `consent`, `endpoint`, `state`, `form-id`, `label`, `button`, `success`. Without JavaScript a page says "This page needs JavaScript." and shows no form.
- **Design.** Buttons, never dropdowns; Lucide icons only; flat fills, no borders (`.markus-notifications-*` in `markus-components.css`, fills mixed from the text colour so both themes work). State is a word and a mark, never colour alone: a list is `On` with a bell or `Off` with a bell-off, and every status line has a check or alert mark and words. After saving, the page says in words what the reader gets ("Your choices are saved. You get: New stories.").
- **Bad link or service down.** A token the function rejects (400) goes to the expired page with `location.replace`; a service that cannot be reached (502, 503, network) is said in words ("Notifications are not available right now. Please try again later.") and is not called expired. Until a Caducus release adds public audiences the function answers 503, so the pages show that message.
- **Not built (decided).** The Slack and Discord sign-in option waits for those channels to be live (PPY-cc015c, PPY-62c937) and for a public-reader site; nothing renders for it today.
- **Rollout.** Enabling the plugin on an existing site needs one full projection to write the pages. Screenshot review with Ryan, Machines on Machines first, comes before any prod rollout (PPY-e28679).

## Turning it on for one site

1. The site's sending stack has the SES identity for `sendingDomain` and the configuration set `papyrus-<siteId>`. For the SES-event rule, the set needs an event destination to the default event bus (the newsletter's destination is an SNS topic).
2. Add the plugin block above to the site's `papyrus.config.ts`.
3. Put the operators parameter (above).
4. Deploy the site's backend once (a normal backend deploy: one new stack and one new environment variable on `content-actions`).

## Tests

`npm run test:notifications-plugin` (synth), `npm run test:notifications-api` (routes), `features_backend/notifications-story-published.feature`, `features_backend/notifications-reader-pages.feature` (the pages and the scripts, run in Node against the projected markup), `procedures/newsroom/tests/test_standard_frontend_notifications_pages.py`, `procedures/newsroom/tests/test_papyrus_notifications_scripts.py` and `features_backend/notifications-function.feature`, and the pytest modules under `src/papyrus_content/notifications/`.
