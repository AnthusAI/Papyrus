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

The route returns 503 until a private durable Chatticus storage runtime is
configured. No Papyrus chat table, queue, runtime composition, schema or IAM
policy has been created here. Before enabling it, the deployment needs an
approved private messaging table and conversation storage, run and deadline
queues, runtime composition using the pinned `chat-server` export, and the
minimum DynamoDB, S3 and SQS permissions for that runtime. The UI's AppSync send
path remains unchanged. The endpoint contract test injects only local storage
and queue fakes and does not verify AWS durability or deployed permissions.

`lib/papyrus-chat-admission.ts` binds the Chatticus admission client to an
injected Papyrus endpoint and fresh-header provider. It requires an
`Authorization` header but leaves the token type and claims to the host. Its
hermetic test proves one POST per explicit send, fresh auth headers on retry,
stable key/body reuse, and no fallback request on auth failure. The current
console does not call this adapter: the live AppSync send path remains in place
until the host endpoint and production identity mapping are separately
implemented and reviewed.

This change does not yet replace the Rust responder, adopt the shared SSE API
in Papyrus, add per-editor transcript isolation, change backend permissions or
implement job/approval continuations. The old backend remains the only chat
writer. Those later gates are defined by the reviewed integration plan in
PR #661; the initiative is not complete when only this UI increment lands.

The dependency is a source commit for review/testing, not a registry release.
Do not merge, release, publish packages or deploy from this task without the
required further approval. PR #660 owns loading, Notification Center and mobile
navigation changes; this increment does not edit those files.
