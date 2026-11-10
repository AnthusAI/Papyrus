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

The plugin's kind `story.published` (`src/papyrus_content/notifications/data/notification-kinds.json`) is class `operator`, so those addresses are the whole audience, and `approval` is carried in the settings for when lists have readers. The `/api/notifications/{subscribe,confirm,preferences,unsubscribe,state}` routes exist (same-origin rule, 400 and 303 rather than 403 and 404 because the edge rewrites those, a site without the plugin answers 404, `lib/notifications-api.ts`), but the function answers every reader action `503 unavailable` and stores nothing until a Caducus release adds public audiences. No page under `/notifications/` exists yet.

## Turning it on for one site

1. The site's sending stack has the SES identity for `sendingDomain` and the configuration set `papyrus-<siteId>`. For the SES-event rule, the set needs an event destination to the default event bus (the newsletter's destination is an SNS topic).
2. Add the plugin block above to the site's `papyrus.config.ts`.
3. Put the operators parameter (above).
4. Deploy the site's backend once (a normal backend deploy: one new stack and one new environment variable on `content-actions`).

## Tests

`npm run test:notifications-plugin` (synth), `npm run test:notifications-api` (routes), `features_backend/notifications-story-published.feature` and `features_backend/notifications-function.feature`, and the pytest modules under `src/papyrus_content/notifications/`.
