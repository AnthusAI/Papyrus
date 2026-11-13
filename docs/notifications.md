# Notifications (the `notifications` plugin)

Status: Built, off everywhere (PPY-44721a, PPY-38be08, public audiences PPY-1081ad). Nothing is enabled on any site. Plan: [plans/public-audiences.md](plans/public-audiences.md). Architecture: `docs/notifications-plan.md` in AnthusAI/Caducus. There is no central service: [Caducus](https://pypi.org/project/caducus/) (`caducus[notify]`, pinned exactly in `amplify/plugins/notifications/function/requirements.txt`) runs inside each site's own stack, with the site's own table.

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
    consent: "I agree to get the emails I choose from Example News and can unsubscribe at any time.",  // the form shows exactly this
    confirmWindowHours: 72,                  // optional; how long an unconfirmed address is kept and the link works
  }],
}
```

`computeRoleArn` comes from `PAPYRUS_COMPUTE_ROLE_ARN` as for the newsletter. Bad settings stop the synth.

The plugin adds one stack, only where it is listed:

| Resource | Notes |
|---|---|
| Table `papyrus-notifications-<siteId>` | retained, customer-managed KMS key with rotation, TTL `expiresAt`, GSIs `byRecipient` and `byList` (a list's confirmed subscribers, keys only), no point-in-time recovery |
| SSM `/papyrus/<siteId>/notifications/recipient-key` | SecureString, created once, never overwritten |
| Functions (Python 3.12, arm64, one bundle with `papyrus_content` and Caducus) | `papyrus-notifications-<siteId>` (router), `-email-`, `-flush-`, `-ses-`, and `-pause-` (only without the newsletter plugin) |
| Queues | the email queue with a dead letter queue, and a dead letter queue for failed asynchronous router invocations; an alarm on each (no alarm action: the account's operator listener reads every alarm) |
| EventBridge rules (default bus) | every minute for the flush; SES events of the site's configuration set, only for mail tagged with this site and a delivery id; the two rate alarms entering ALARM (only without the newsletter plugin) |
| Alarms | one on each dead letter queue; without the newsletter plugin also the bounce-rate and complaint-rate alarms `papyrus-notifications-<siteId>-bounce-rate` and `-complaint-rate` (same metrics and thresholds as the newsletter's) |
| IAM | the router reads the one `getPublishedItem` AppSync field; the email function sends only from the configured address through the site's identity and set; the router may remove an address from the SES account suppression list (a reader's own opt-in after a bounce); only the CMS compute role may invoke the router (a resource policy); `content-actions` may invoke that one function |

No GraphQL model or operation, so no AppSync realtime. The mail carries the site's own theme (`THEME_JSON`, rendered by `papyrus_content.email_render`, passed to Caducus as its renderer).

## The publish path

`src/papyrus_content/publish_alerts.py` is the only place a publish announces. Beside the newsletter, `announce_published` asynchronously invokes the router (`PAPYRUS_NOTIFICATIONS_FUNCTION`, set on `content-actions` by the plugin) with `{"task": "story-published", "itemId", "lineageId", "publishedItemId", "eventId": "story.published:<lineage>"}`. The same rules as the newsletter's alerts apply: only a real publish (`PublishResult.changed`), after the page is live (a failed projection announces from its retry), never on unpublish, edits, reprojection or bulk imports, a no-op when the plugin is off, and every error is logged and swallowed with short timeouts. Each function is tried even if the other failed.

The router reads the published item, drops it unless some list's rule matches (`sections`, `tags`, `types`, as for the newsletter), and hands Caducus a `story.published` event whose id comes from the lineage and which names the matching lists. Caducus dedupes on that id in the site's table, so a publish, unpublish and publish again mails once. The event fans out page by page over the `byList` index through the email queue; a reader on several matching lists gets one message.

## Readers: Caducus public audiences

The kind `story.published` (`src/papyrus_content/notifications/data/notification-kinds.json`) is class `public`: its audience is the readers who subscribed to the matching lists and confirmed. Readers, lists, consent evidence, suppression, tokens and abuse limits are Caducus's (`caducus.notify.audience`, [docs/public-audiences.md in AnthusAI/Caducus](https://github.com/AnthusAI/Caducus/blob/develop/docs/public-audiences.md)); the plugin builds the audience from the site's settings (`public.py`, `links.py`) and hands each reader action to `caducus.notify.handlers.public.dispatch`. The operators parameter no longer receives new stories.

- **Routes.** `/api/notifications/{subscribe,confirm,preferences,unsubscribe,state}` (`lib/notifications-api.ts`): the same-origin rule, 400 and 303 rather than 403 and 404 because the edge rewrites those, and a site without the plugin answers 404. Subscribe answers `202 check_email` for anything valid-looking, `400 invalid_email`, `invalid_lists` or `invalid_consent` (the wording is not the configured `consent`), and `429 slow_down` when one network sends far more than this site's readers do. The route passes the site origin to the function as consent evidence.
- **Confirmation.** One themed message with a button to `<base>/notifications/confirm/?token=`; the page's button POSTs. Nothing else is sent until the reader confirms; the link works for `confirmWindowHours`, and an unconfirmed address is deleted then (DynamoDB TTL).
- **Story mail** carries `List-Unsubscribe` (the one-click URL `/api/notifications/unsubscribe?t=&l=`) and `List-Unsubscribe-Post: List-Unsubscribe=One-Click`, and a footer with the reader's preferences and unsubscribe page links and the postal address. Links carry a signed token, never an address.
- **Bounces and complaints.** The `-ses-` function passes a permanent bounce or a complaint to Caducus, which suppresses the reader and unsubscribes them from every list. A reader who turns a list on again from their manage link lifts it, and the router also removes the address from the SES account suppression list.
- **Erasure and export.** A reader deletes their data from the preferences page. Admin export and erasure are Caducus calls (`PublicAudience.export` and `erase`) that no public route sends; the newsroom panel that calls them with the admin group checked comes with PPY-6b2d35.

## Sending as the site

Notifications reuse what the site's newsletter sending stack ([infra/newsletter](../infra/newsletter/README.md)) created in the same account: the SES identity for `sendingDomain` and the configuration set `papyrus-<siteId>`. No sending authorization, no second set, no central sender. One set means one reputation and one pause per site.

- **Which sites have an identity.** [config/newsletter-sending-identities.json](../config/newsletter-sending-identities.json) lists every site under `infra/amplify-app-shell/examples` with its sending domain or `null`, and `scripts/test-sending-identities.ts` fails when a site is missing from it. On 2026-11-04 the sites with no stack were Anth.us and Threat Intelligence (and the Pretext example). Deploy the stack for a site before enabling the plugin there.
- **Tags.** Every message carries `site`, `kind` and `delivery` (`SiteMailer` adds `site`; Caducus adds the other two). The newsletter's event handler already ignores any event without a valid `sub` tag, and this plugin ignores any event whose `site` tag is not its own or that has no `delivery` tag, so the two consumers of the set's events never touch each other's mail (`features_backend/notifications-site-identity.feature`).
- **Events.** The SES event rule needs the stack's `EventTransport` set to `both` (the newsletter keeps its SNS topic; the default bus gets the same events). The `-ses-` function maps a message back to its delivery through a `MSG#<messageId>` row written when the message is sent, and moves the delivery to `delivered`, `bounced` (permanent), `delayed` (transient bounce or delay), `complained` or `rejected`. A status never moves backward, because SES delivers out of order.
- **Pause.** A site with the newsletter plugin keeps its alarms and pause. A site with notifications only gets the same two rate alarms from this plugin, and the `-pause-` function turns sending off on the configuration set when either enters ALARM. Nobody pauses by hand and nobody resumes automatically: lifting a pause is `aws sesv2 put-configuration-set-sending-options --configuration-set-name papyrus-<siteId> --sending-enabled` by a person, after reading why. Admins are told by the account's operator listener, which reads every alarm on the default bus.
- **A send on a paused set** is refused by SES with `SendingPausedException` (listed for `SendEmail` in botocore's sesv2 service model; `SiteMailer` catches only that `ClientError` code). The delivery is logged `failed` with the reason `sending is paused for configuration set papyrus-<siteId>` and is not retried. The AWS documentation describes the exception for the account's sending; that it is also what a paused configuration set returns is confirmed by the first forced pause on Machines on Machines (any other code surfaces as a retried delivery, and the dead letter alarm tells admins).
- **Footer.** The postal address comes from SSM exactly as for the newsletter (`/papyrus/<siteId>/email/postal-address`, else `/papyrus/email/postal-address`). The confirmation (account class) prints none. Public-class mail (story mail to readers) is refused with the reason `postal address missing` when neither parameter holds one, and otherwise carries the address in the footer with the reader's own manage and unsubscribe links.
- **Capacity** is shared by the account (14 messages a second and 50,000 a day on the 2026-11-04 reading). Each site's pacer reads `MaxSendRate` and cannot see the others, so Caducus's throttling backoff keeps them honest; watch it on batch sends. There is no fixed cap: ramp Machines on Machines first, then the rest.

## Turning it on for one site

1. The site's sending stack exists (`newsletter-sending-identities.json`; if the domain is `null`, deploy it first, see [infra/newsletter](../infra/newsletter/README.md)) and its `EventTransport` is `both`, so the SES-event rule has a destination (the newsletter keeps working on the topic).
2. Add the plugin block above to the site's `papyrus.config.ts`.
3. Put the postal address parameter (public mail is refused without it). The operators parameter stays for operator-class kinds.
4. **The forced pause drill has passed** on a test configuration set (PPY-a85725): with the set's sending off, a send to the SES simulator shows the delivery `failed` with "sending is paused", which confirms the `SendingPausedException` code `SiteMailer` relies on; with sending on again, the next send goes out. Until then no site lists the plugin with readers' lists.
5. Deploy the site's backend once (a normal backend deploy: one new stack and one new environment variable on `content-actions`).
6. Acceptance on Machines on Machines: a real inbox shows SPF, DKIM and DMARC pass; an SES simulator bounce (to the SES bounce simulator mailbox) shows `bounced` in the site's delivery log and leaves the newsletter's ledger alone.

## Tests

`npm run test:notifications-plugin` (synth), `npm run test:notifications-api` (routes), `features_backend/notifications-story-published.feature`, `notifications-function.feature`, `notifications-site-identity.feature` and `notifications-public-audience.feature`, and the pytest modules under `src/papyrus_content/notifications/`.
