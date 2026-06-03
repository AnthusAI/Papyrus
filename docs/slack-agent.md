# Papyrus Slack Agent Channel

The Slack app is a third agent channel alongside the web console and inbound email.
All three enqueue `console_chat_turn` messages on the `consoleChat` feed; the
**console-chat-responder** Lambda runs the same agent loop and **`execute_tactus`**
tool surface as the editor console.

**Tone:** Slack uses the same open-ended editorial assistant stance as the web console
(questions, commands, knowledge search). Inbound **email** remains citation-oriented
reference intake. Slack prompts explicitly exclude web UI navigation (`papyrus://`,
`papyrus.web.*`); filing references is on user intent, not automatic for every URL.

## Architecture

```mermaid
sequenceDiagram
  participant Slack
  participant Events as slack-events Lambda
  participant DDB as Message / MessageThread
  participant Responder as console-chat-responder
  participant Delivery as slack-delivery Lambda

  Slack->>Events: event_callback (signed)
  Events->>DDB: create USER console_chat_turn (PENDING)
  DDB-->>Responder: stream INSERT
  Responder->>Responder: OpenAI + execute_tactus
  Responder->>DDB: ASSISTANT turn COMPLETED
  DDB-->>Delivery: stream INSERT/MODIFY
  Delivery->>Slack: chat.postMessage (thread)
```

## Enable in Amplify

Set sandbox or pipeline env vars:

- `PAPYRUS_ENABLE_SLACK=true`
- `PAPYRUS_SLACK_SIGNING_SECRET` (Amplify secret via `npx ampx secret set`, not `.env` alone)
- `PAPYRUS_SLACK_BOT_TOKEN` (Amplify secret, `xoxb-…`, same `ampx secret set` flow)

`.env` is for local development only. Deployed Lambdas read secrets from SSM using
`AMPLIFY_SSM_ENV_CONFIG`; placeholders like `<value will be resolved during runtime>`
are resolved at cold start.
- Optional: `PAPYRUS_SLACK_ALLOWED_USER_IDS` (comma-separated Slack user IDs)
- `PAPYRUS_CONSOLE_RESPONSE_TARGET=cloud` (same as email/console)

Deploy; `amplify/backend.ts` adds `custom.slack.eventsUrl` in Amplify outputs (Lambda function URL).
Point the Slack app **Event Subscriptions** request URL at that URL.

### Production (`main` branch)

1. Merge or deploy `main` via Amplify Gen 2 (push to `main` triggers the pipeline).
2. In the Amplify console for the **main** backend, set branch env vars and secrets above.
   Slack Lambdas are created only when `PAPYRUS_ENABLE_SLACK=true`.
3. After a successful deploy, open **Backend deployments → Outputs** (or `amplify_outputs`)
   and copy `custom.slack.eventsUrl` into the Slack app Event Subscriptions request URL.
4. Reinstall the Slack app to the workspace if you changed bot scopes.

### Slack app scopes (minimum)

- `app_mentions:read`
- `chat:write`
- `im:history`, `channels:history` (for DMs / public channels you use)

Subscribe to bot events: `message.im`, `message.channels`, `app_mention`.

## Shared code

| Module | Role |
|--------|------|
| `src/papyrus_newsroom/console_chat_enqueue.py` | Shared GraphQL enqueue for multi-channel agents |
| `src/papyrus_newsroom/slack_agent.py` | Slack verify, prompt, enqueue, delivery |
| `amplify/functions/shared/console-chat-enqueue.ts` | TypeScript enqueue (slack-events handler) |
| `amplify/functions/slack-events/` | Signed Events API ingress |
| `amplify/functions/slack-delivery/` | Post assistant replies to Slack threads |

Email continues to use `email_submission_replies.enqueue_console_chat_*`; new channels
should call `console_chat_enqueue.enqueue_console_chat_turn` (Python) or
`console-chat-enqueue.ts` (Lambda TypeScript).

## Operations

- **Delivery loop guard:** `slack-delivery` ignores DynamoDB `MODIFY` events that only touch
  metadata on an already-`COMPLETED` assistant turn (for example after `slackDeliveredAt` is
  written). Without this, marking delivery complete re-triggers the stream and spams Slack.
- Idempotency: Slack `event_id` maps to deterministic `message-console-slack-*` ids.
- Authorization: when `PAPYRUS_SLACK_ALLOWED_USER_IDS` is empty, all non-bot users are accepted (dev only).
- Truncation: outbound Slack text is capped at 12k characters.
