# Shared newsroom chat UI

First increment of PPY-a438d0 / PPY-61ee23. The newsroom console consumes
Chatticus's reusable `chat-react` surface and scoped `chat.css` from an exact
Git commit dependency. The current consumer candidate pins Chatticus commit
`2d669be2d4da04ea0b96181d95c3f198e56cf474`, which includes the shared server
core extraction and recovery fixes on top of PR #637 and PR #636. Papyrus does
not copy Chatticus components or its model loop.

`components/papyrus-console-conversation.tsx` maps console presentation records
into shared messages. `papyrus-console-shell.tsx` still owns its existing
Cognito session, thread/message persistence, AppSync updates, model selection,
page context, editorial tool cards and navigation. Those host actions are
passed through presentation hooks. The shared component owns ordinary
transcript/markdown rendering, input/send behavior and scroll handling.

The host palette is mapped through `--chatticus-chat-*` custom properties in
`papyrus-console-conversation.css`. The shared stylesheet is scoped to the chat
surface; it has no page reset. The root layout loads it so authenticated console
use outside `/newsroom` is also styled. Both the engine Next config and
`withPapyrus()` transpile Chatticus's TypeScript source exports for site consumers.

Run the hermetic browser acceptance with:

```
node node_modules/@cucumber/cucumber/bin/cucumber.js --config cucumber-shared-chat.cjs
node scripts/test-with-papyrus-transpile.mjs
```

These scenarios render the real Papyrus adapter with the installed Chatticus
package in a temporary local browser fixture. They prove a send reaches the
host once, shared markdown refuses executable links, and editorial reference
actions remain host callbacks. They do not access AWS or make model calls.

`app/api/newsroom/chat/[...path]/route.ts` is an undeployed site-owned gateway
candidate for Chatticus message send/list and turn event/stream routes. It opens
the existing sealed Prospectus session, rechecks the selected Account's active
Papyrus product and fresh `console:read` or `console:write` authorization, and
derives an opaque site/Account tenant and per-editor principal on the server.
Chatticus's shared core then enforces channel participation for transcript and
turn reads. Client-supplied tenant and author values are never trusted.

The private UI candidate uses a same-origin browser adapter and the route returns
503 until its private durable Chatticus runtime is configured. The feature is
default-off; `PAPYRUS_PRIVATE_CHAT_ENABLED=true` switches the console to it, and
without that setting the existing AppSync path remains unchanged. The runtime
candidate is in `infra/shared-chat-runtime`; it defines private messaging and
conversation-index tables, a versioned private session bucket, run/probe queues,
worker entry points and scoped policies. Its queue event mappings are disabled
by default, so the candidate cannot produce replies until they are deliberately
enabled. No production stack, role or site environment has been changed. The
endpoint and worker tests use injected local stores/queues; they do not verify
AWS durability or deployed permissions.

`lib/papyrus-chat-admission.ts` binds the Chatticus admission client to an
injected Papyrus endpoint and fresh-header provider. It requires an
`Authorization` header but leaves the token type and claims to the host. Its
hermetic test proves one POST per explicit send, fresh auth headers on retry,
stable key/body reuse, and no fallback request on auth failure. The current
console does not call this adapter: the live AppSync send path remains in place
until the host endpoint and production identity mapping are separately
implemented and reviewed.

The private path derives site, account and editor identity from the sealed
Prospectus session and uses per-editor channels. It does not forward bearer
tokens or accept client-supplied authorship. The old AppSync path remains active
until the feature flag and private runtime are configured in a reviewed
deployment. This increment does not change backend permissions or implement
job/approval continuations; those gates remain in PR #661's integration plan.

The dependency is a source commit for review/testing, not a registry release.
Do not merge, release, publish packages or deploy from this task without the
required further approval. PR #660 owns loading, Notification Center and mobile
navigation changes; this increment does not edit those files.
