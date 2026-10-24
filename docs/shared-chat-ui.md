# Shared newsroom chat UI

First increment of PPY-a438d0 / PPY-61ee23. The newsroom console now consumes
Chatticus's reusable `chat-react` surface and scoped `chat.css` from an exact
Git commit dependency. The same implementation is used by Chatticus's own
workspace; Papyrus does not copy its components or its model loop.

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

This change does not yet replace the Rust responder, adopt the shared SSE API
in Papyrus, add per-editor transcript isolation, change backend permissions or
implement job/approval continuations. The old backend remains the only chat
writer. Those later gates are defined by the reviewed integration plan in
PR #661; the initiative is not complete when only this UI increment lands.

The dependency is a source commit for review/testing, not a registry release.
Do not merge, release, publish packages or deploy from this task without the
required further approval. PR #660 owns loading, Notification Center and mobile
navigation changes; this increment does not edit those files.
