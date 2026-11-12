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
| Functions (Python 3.12, arm64, one bundle with `papyrus_content` and Caducus) | `papyrus-notifications-<siteId>` (router), `-email-`, `-flush-`, `-ses-`, and `-pause-` (only without the newsletter plugin) |
| Queues | the email queue with a dead letter queue, and a dead letter queue for failed asynchronous router invocations; an alarm on each (no alarm action: the account's operator listener reads every alarm) |
| EventBridge rules (default bus) | every minute for the flush; SES events of the site's configuration set, only for mail tagged with this site and a delivery id; the two rate alarms entering ALARM (only without the newsletter plugin) |
| Alarms | one on each dead letter queue; without the newsletter plugin also the bounce-rate and complaint-rate alarms `papyrus-notifications-<siteId>-bounce-rate` and `-complaint-rate` (same metrics and thresholds as the newsletter's) |
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

The plugin's kind `story.published` (`src/papyrus_content/notifications/data/notification-kinds.json`) is class `operator`, so those addresses are the whole audience, and `approval` is carried in the settings for when lists have readers. The `/api/notifications/{subscribe,confirm,preferences,unsubscribe,state}` routes exist (same-origin rule, 400 and 303 rather than 403 and 404 because the edge rewrites those, a site without the plugin answers 404, `lib/notifications-api.ts`), but the function answers every reader action `503 unavailable` and stores nothing until a Caducus release adds public audiences. No page under `/notifications/` exists yet.

## Sending as the site

Notifications reuse what the site's newsletter sending stack ([infra/newsletter](../infra/newsletter/README.md)) created in the same account: the SES identity for `sendingDomain` and the configuration set `papyrus-<siteId>`. No sending authorization, no second set, no central sender. One set means one reputation and one pause per site.

- **Which sites have an identity.** [config/newsletter-sending-identities.json](../config/newsletter-sending-identities.json) lists every site under `infra/amplify-app-shell/examples` with its sending domain or `null`, and `scripts/test-sending-identities.ts` fails when a site is missing from it. On 2026-11-04 the sites with no stack were Anth.us and Threat Intelligence (and the Pretext example). Deploy the stack for a site before enabling the plugin there.
- **Tags.** Every message carries `site`, `kind` and `delivery` (`SiteMailer` adds `site`; Caducus adds the other two). The newsletter's event handler already ignores any event without a valid `sub` tag, and this plugin ignores any event whose `site` tag is not its own or that has no `delivery` tag, so the two consumers of the set's events never touch each other's mail (`features_backend/notifications-site-identity.feature`).
- **Events.** The SES event rule needs the stack's `EventTransport` set to `both` (the newsletter keeps its SNS topic; the default bus gets the same events). The `-ses-` function maps a message back to its delivery through a `MSG#<messageId>` row written when the message is sent, and moves the delivery to `delivered`, `bounced` (permanent), `delayed` (transient bounce or delay), `complained` or `rejected`. A status never moves backward, because SES delivers out of order.
- **Pause.** A site with the newsletter plugin keeps its alarms and pause. A site with notifications only gets the same two rate alarms from this plugin, and the `-pause-` function turns sending off on the configuration set when either enters ALARM. Nobody pauses by hand and nobody resumes automatically: lifting a pause is `aws sesv2 put-configuration-set-sending-options --configuration-set-name papyrus-<siteId> --sending-enabled` by a person, after reading why. Admins are told by the account's operator listener, which reads every alarm on the default bus.
- **A send on a paused set** is refused by SES with `SendingPausedException`; the delivery is logged `failed` with the reason `sending is paused for configuration set papyrus-<siteId>` and is not retried. The exact error code is taken from the SES v2 API reference and not yet seen on a live paused set: the first forced pause on Machines on Machines confirms it (a different code would surface as a retried `queued` delivery, and the dead letter alarm tells admins).
- **Footer.** The postal address comes from SSM exactly as for the newsletter (`/papyrus/<siteId>/email/postal-address`, else `/papyrus/email/postal-address`). Operator-class mail (everything today) prints none. Public-class mail (readers; arrives with Caducus public audiences) is refused with the reason `postal address missing` when neither parameter holds one, and otherwise carries the address under the reason sentence. Per-recipient manage and unsubscribe links wait for Caducus to supply recipient tokens.
- **Capacity** is shared by the account (14 messages a second and 50,000 a day on the 2026-11-04 reading). Each site's pacer reads `MaxSendRate` and cannot see the others, so Caducus's throttling backoff keeps them honest; watch it on batch sends. There is no fixed cap: ramp Machines on Machines first, then the rest.

## Turning it on for one site

1. The site's sending stack exists (`newsletter-sending-identities.json`; if the domain is `null`, deploy it first, see [infra/newsletter](../infra/newsletter/README.md)) and its `EventTransport` is `both`, so the SES-event rule has a destination (the newsletter keeps working on the topic).
2. Add the plugin block above to the site's `papyrus.config.ts`.
3. Put the operators parameter (above), and the postal address parameter if the site will ever send public mail.
4. Deploy the site's backend once (a normal backend deploy: one new stack and one new environment variable on `content-actions`).
5. Acceptance on Machines on Machines: a real inbox shows SPF, DKIM and DMARC pass; an SES simulator bounce (to the SES bounce simulator mailbox) shows `bounced` in the site's delivery log and leaves the newsletter's ledger alone.

## Tests

`npm run test:notifications-plugin` (synth), `npm run test:notifications-api` (routes), `features_backend/notifications-story-published.feature` and `features_backend/notifications-function.feature`, and the pytest modules under `src/papyrus_content/notifications/`.
