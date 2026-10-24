# Shared newsroom chat UI

First increment of PPY-a438d0 / PPY-61ee23. The newsroom console consumes
Chatticus's reusable `chat-react` surface and scoped `chat.css` from an exact
Git commit dependency. Papyrus now pins Chatticus PR #637's head, which stacks
the message admission transport on PR #636's UI exports. Papyrus does not copy
Chatticus components or its model loop.

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

The separate site-hosted auth boundary is only a code-local contract so far;
see [shared chat trust contract](shared-chat-trust-contract.md). Its injected
verifier and membership fakes are test-only. This increment does not wire a
route or replace the current AppSync send path.

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
