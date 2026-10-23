# Chatticus chat in the Papyrus newsroom: integration plan

Planning only • 23 October 2026 • PPY-de11ec / PPY-eeb023

**Recommendation:** make Chatticus the owner of shared chat behavior and let Papyrus own the editorial application. Extract a small client/protocol package and a React chat surface; provide the durable server core from Chatticus with Papyrus-specific auth, context, tools and job adapters. Do not embed the whole Chatticus workspace, copy its components into Papyrus, or build another Papyrus agent loop.

**Use the existing TypeScript Pi Durable implementation; do not introduce a Python migration prerequisite.** The user clarified after reviewing the plan that Pi Durable appears to be TypeScript-only. The inspected code confirms TypeScript `@earendil-works/pi-durable` 1.0.2; no Python package identity was supplied or verified. Earlier PPY issue descriptions saying PyAgents/PyDurable are stale terminology to reconcile, not evidence of an available Python implementation. Extract the React surface and HTTP/SSE client first, independently of the runner. Plan later server extraction around the existing Chatticus TypeScript core, with an explicit decision on how that shared dependency fits Papyrus's Python-first backend policy. Do not build a second chat loop in Python merely to match the old wording.

**Handoff state:** implementation is paused at the user's request. No production code was changed. Local-only test scaffolding reached the expected red state because the proposed packages do not yet exist; it is not included in this planning delivery. Resume implementation on the user's Mac from the planning branches, using Kanbus and executable specifications before production changes. Preserve the other worker's ownership of newsroom loading states, Notification Center focus/removal of Go to, and mobile navigation alignment.

## Read the illustrations

These are actual Archify standalone HTML diagrams, produced by the installed personal Archify skill. Links are relative to this plan:

1. [Papyrus today](architecture/chatticus-chat/papyrus-current/papyrus-current.html): an independent chat engine.
2. [Chatticus today](architecture/chatticus-chat/chatticus-current/chatticus-current.html): durable turns, stored events and reconnecting UI.
3. [Proposed architecture](architecture/chatticus-chat/proposed/proposed.html): shared chat with application adapters.
4. [Message and tool round trip](architecture/chatticus-chat/editor-roundtrip/editor-roundtrip.html).
5. [Job completion, approval and replay](architecture/chatticus-chat/editor-continuation/editor-continuation.html).

The proposed architecture was opened through Archify's supported `deliver ... --open` command and verified visible in Safari. Its verified local URL is `file:///Users/home/Documents/Codex/2026-10-23/task-4/.archify/proposed/proposed.html`. This is a standalone local file viewer, not a hosted service; no server must remain running and nothing was published externally. The installed CLI rejects `finalize --open`; its supported `deliver --open` invocation succeeded. Open any of the other HTML files directly in a desktop browser. The viewer supports light/dark themes and full-diagram PNG, JPEG, WebP and dual-theme SVG export through its Export menu. These static diagrams do not enable trace motion, so WebM is not part of this delivery. Exports are viewer capabilities; no exported image or video is claimed here. Each folder retains `candidate.json`, delivery/provenance receipts, finalize receipts and browser-check evidence. See [artifact manifest](architecture/chatticus-chat/manifest.json) for absolute paths and hashes. All five final artifacts pass showcase validation, delivery, strict artifact checks and automated browser checks; no perceptual review is claimed. The sequence is split into two parts to preserve every step while meeting Archify’s measured readability and viewport contracts.

## Evidence and scope

The executor reported `BlackbookM1`, `arm64`, at `/Users/home/Documents/Codex/2026-10-23/task-4`. No workers were launched and no model substitution was requested. Requested execution was GPT-6.1 Sol, medium; a separate model-settings introspection interface was not exposed to this task.

Read-only inspection used isolated local clones, not the shared working trees. A subsequent fetch in each isolated clone confirmed these revisions still match remote `develop`:

| Repository | Revision | Local evidence copy |
| --- | --- | --- |
| `https://github.com/AnthusAI/Papyrus.git` | `f427a8bd92ec651095bce8b84ba810220b04fb8a` | `../papyrus-plan` |
| `git@github.com:AnthusAI/Chatticus.git` | `9562cccaacbb97c545100e14132538a29e6f0e68` | `../chatticus-plan` |

Repository root AGENTS.md and CONTRIBUTING_AGENT.md were read, including current Papyrus guidance rather than only its stale shared checkout. Installed personal skills were inventoried, including `~/.agents/skills`; Archify was found at `/Users/home/.agents/skills/archify/SKILL.md`. Papyrus `.agents/skills` contains copywriting, editorial-copyedit-cycle and reporting; Chatticus has no `.agents/skills` directory. Editorial-copyedit-cycle and knowledge-query were read for context/permission design. No live policy packs, credentials or private editorial text were fetched. Architectural claims concern source code, not proof of deployed behavior.

The current PPY initiative and M1–M6 records were read through `kbs`, never by reading issue JSON. All seven are open. The descriptions verify the requested ownership, earlier Python wording, computer-free embed, per-editor/site transcripts, permissions, approvals and Slack retirement goals. M3's description requires the client and auth bridge. `kbs show --json` confirms M2 and M3 both have empty dependency arrays; their records were created on 21 October, not today. Treat ordering below as proposed, not as existing board edges. The dependency-tree command failed on short IDs, so the issue JSON returned by the supported CLI was used to verify the relationship fields. Initial Chatticus board searches found no PyDurable issue or matching published-core work item. The handoff subsequently created open planning records `chatticus-abde29` and `chatticus-080b0e`, carried on the Chatticus handoff branch. Saved Kanbus command output is in `docs/architecture/chatticus-chat/evidence/`; later handoff comments are on the planning branch records.

## What exists today

| Area | Verified implementation | Consequence |
| --- | --- | --- |
| Papyrus console | `components/papyrus-console-shell.tsx:679–695,788–852` creates Message records and subscribes to changes. It includes thread selection, current UI context, model selection and optimistic messages. | Preserve useful host behavior, replace the chat state/transport path rather than layering a second chat loop under it. |
| Papyrus storage | `amplify/data/schema.ts:1664–1746` defines Message and MessageThread, indexes and group authorizations. `semanticLayer=working_memory` and `searchVisibility=private` are metadata. | Metadata does not establish editor-only access. Per-editor/site privacy needs real server authorization and storage keys. |
| Papyrus engine | `amplify/functions/console-chat-responder/src/main.rs:259–430` handles INSERT, claims a message, locks its thread, runs its own model loop and writes progress/completion through GraphQL. `resource.ts:77–136` configures a two-minute container Lambda and service-role access. | This is an independent engine, not a wrapper around Chatticus. Do not call it durable across crashes merely because transcripts persist. |
| Papyrus tools | Responder Dockerfile installs `tactus==0.44.1`; `py/execute_tactus_runner.py:66–79` calls `execute_tactus_harnessed`; `src/papyrus_newsroom/tactus_runtime.py:2075–2159` builds the Papyrus runtime. | Reuse existing business operations, but an arbitrary Tactus execution tool is too broad to be the new editor permission boundary. |
| Papyrus Slack | `slack-events/handler.ts:18–110` verifies events and deduplicates by event ID before IAM enqueue. Shared enqueue writes MessageThread, Message and a body attachment. `slack-delivery/handler.py:50–108` dispatches completed assistant replies. | Transport adapters can survive; the second model loop must eventually go. Slack identity is not already an editor Cognito identity. |
| Existing auth shortcuts | `lib/console-chat-client.ts:300–320,1270–1299` includes read retry from userPool to apiKey; the same file introspects schema and supports legacy selection shapes. | Do not port these shortcuts into the embed. User authorization failure must fail closed. This is a source finding, not a claim an API key can successfully read private rows. |
| Chatticus turn protocol | `conversation/src/http/routes/messages.ts:89–119` admits a human message with optional Idempotency-Key and returns turn_id. `turn-stream.ts:85–190` replays stored events after Last-Event-ID and closes at terminal events. | Reuse these semantics. POST admission and GET SSE are separate requests; the POST is not itself the long SSE response. |
| Chatticus client | `web/lib/sse.ts` uses authorized fetch and SSE parsing. `resumable-turn-stream.ts:25–98` reconnects with a cursor, drops duplicate sequences and bounds retry. | This is the clearest first extraction seam. Add stable send idempotency to the ordinary message client; server support alone does not mean its current postMessage helper sends a key. |
| Chatticus durability | `conversation/src/pi/session.ts:10–75` opens a fenced IndexedStorage session. `turn/executor.ts:191–275` owns the Pi harness, queued turn attempts, progress and handoff. `storage/indexed-storage.ts` uses S3 data and a DynamoDB index. | Persisted events and committed transcript are distinct from temporary token text. Reuse fence/recovery behavior, not merely a streaming parser. |
| Chatticus tool gate | `conversation/src/pi/gate.ts:1–45,49–86` checks a current turn grant, member standing and exact-action approval before execution. Its capability mappings include computer/workspace/product tools. | Reuse the gating lifecycle, but supply a Papyrus capability vocabulary and backend enforcement. This is not already an editor tool bridge. |
| Computerless seam | `turn/types.ts:95–103` still requires computer dependencies; `turn/executor.ts:211–217` installs remote computer tools when no override is supplied. | “Computerless worker” does not mean “computer capability omitted.” The embed must register only Papyrus tools and have no computer startup dependency. |
| Chatticus React surface | `ChatticusAssistantRuntime.tsx` bridges an external store to assistant-ui; `ChatticusAssistantThread.tsx` imports product activity, cost and other workspace code. Root package exports workspace/UI primitives and brand CSS, but not a complete independent chat SDK; root is private. | Existing exports are a starting point, not a shippable generic package. Replace app aliases and product dependencies at the seam. Preserve the private marketing consumer's current exports. |
| Chatticus auth | `http/user-principal.ts` resolves Cognito and membership; `http/acting-user.ts` checks acting user and channel membership. `routes/turns.ts:145–160` resolves a principal then looks up the tenant-scoped turn. | The embed must also enforce the channel/editor owner on every turn/event/SSE lookup. Tenant scoping alone is insufficient for the requested privacy. |
| Background work | `docs/procedure-runner.md:1–53` describes a cloud runner, published procedures/skills, persisted ProcedureRun state, deadline and service-role GraphQL access. | Reuse backend jobs. Editor-scoped delegation and general job-to-chat continuation remain new work. No generic durable progress callback bridge was verified. |

## Compare the viable approaches

| Approach | Benefit | Cost / problem | Recommendation |
| --- | --- | --- | --- |
| Embed the whole Chatticus app or iframe a hosted workspace | Small initial UI diff | Two auth/tenant systems, roster/computer baggage, weak editorial integration and separate hosting dependency | Reject for the intended product. A link to Chatticus is not the requested pane. |
| Share protocol/client/UI; keep the Papyrus Rust loop | Fastest visible pane; limited extraction | Leaves the central duplication and two different recovery/tool semantics | Only a temporary bounded migration stage, never the final architecture. |
| Chatticus packages deployed with Papyrus; host adapters for editorial work | One chat implementation; site deployment, identity and content remain coherent | Requires packaging, real computer opt-out and a server-hosting boundary | Recommended end state. |
| Central hosted Chatticus chat service for all Papyrus sites | One server deployment to upgrade | Cross-service trust, data residency, availability and auth delegation become immediate dependencies | Revisit only if there is an operational need; not required for DRY. |

A shared library does not require a shared SaaS service. Deploy the same versioned core beside each Papyrus site's backend using request/turn-scoped compute, a durable queue, private event/transcript storage and job continuations. There is no always-on server or browser. Active execution, storage and requests still cost money; “no idle floor” does not mean zero storage cost.

## Minimum package boundary

Proposed package names are illustrative; none is being published here. Keep these three release units in the Chatticus repository, not a new cross-product monorepo:

| Unit | Owns | Excludes |
| --- | --- | --- |
| `@anthusai/chatticus-chat-client` | Versioned wire schema/fixtures, messages/turn DTOs, SSE parse/reconnect/dedup, committed transcript reconciliation and a transport accepting base URL plus async auth headers | Amplify configuration, global ActiveOrg, bot roster, Papyrus domain types, React and credentials stored in state |
| `@anthusai/chatticus-chat-react` | Controlled composer/transcript, streaming status, retry/error/tool cards, approval rendering slots and accessible interaction | Login UI, publication routing, pane/window placement, global CSS reset, product cost/roster/computer panels |
| Chatticus durable server core | Turn admission/idempotency, queued execution, attempt fencing/recovery, event journal, session persistence, tool dispatch lifecycle and durable approval wait/resume | Editorial policies, publication objects, arbitrary IAM operations, computers, workspace, household membership and fixed product prompt |

The later server core should extract the existing TypeScript Pi Durable implementation, following the user's latest clarification rather than inventing a Python migration. UI/client extraction has no Python dependency: keep model/harness imports outside the client and React entry points, and test the packed surface with an injected fake transport. Specify the shared protocol and replay/recovery conformance fixtures from the existing TypeScript path now. In the later server phase, extract that core in Chatticus and make Chatticus itself consume it before Papyrus depends on that server core. Do not independently reimplement a Python chat loop inside Papyrus and call that reuse. Update PPY-de11ec's stale Python terminology and reconcile Papyrus's Python-first backend rule before adding a new server host there. A dependency on the shared TypeScript core needs an explicit hosting boundary; it does not require rewriting Papyrus's Python business operations.

Start with concrete constructor dependencies: principal/scope resolver, transcript/event/session store, queue, model runner, tool registry, context provider and approval policy. They describe real external effects. Keep one default implementation for each required storage/queue binding. Do not create a general plugin marketplace, arbitrary workflow DSL, multiple database backends, separate package for every interface or a runtime abstraction merely to hide the actual TypeScript dependency.

| Capability | Classification |
| --- | --- |
| Message admission, turns, idempotency, event replay and client reducer | Core |
| Durable model/tool execution, terminal reconciliation, transcript compaction | Core |
| Approval identity/state and durable pause/resume | Core contract; application policy and widgets supplied by adapter |
| Auth verifier, tenant membership/ownership resolution | Adapter; Chatticus and Papyrus each provide one |
| Editorial context, policy packs, tools, procedure/assignment jobs | Papyrus adapter; shared core sees typed context/tool results |
| Computer escalation and associated approval controls | Optional Chatticus capability; absent in Papyrus |
| Named-bot roster, household task board, browser sessions, screens, workspace | Chatticus product only |
| Routines and voice | Leave out of first embed; optional later only if a consumer needs them |
| Cost/activity rendering | Generic activity may be shared; product cost ledger is an optional slot |

## Papyrus adapts identity, context and authority

The Papyrus root newsroom shell hosts one controlled pane. The UI/loading owners retain placement, loading states and editor rollout; this plan only defines the dependency contract. A pop-out should initially mean a dockable in-page panel. A separate browser window needs an explicit UX decision and multi-window tests; it is not implied to be implemented today.

The browser obtains the current signed-in Cognito session through Papyrus, and sends it to the site's chat API. The server verifies signature, issuer, audience and expiry, resolves the actual Account/site/publication membership and editor/admin permissions, and derives actor identity. Never trust an email label, an author ID or a site/Account value supplied by the model. Store and authorize by `(accountId, siteId, editorSub, channelId)`; use immutable identifiers, not hostnames or mutable labels. `deskId` and related legacy code identifiers map to selected newsroom-section context, not to a security boundary or a second tenant. Papyrus prose should use “publication” or “section” per current AGENTS.md.

Resolve page context to typed anchors: current route, item lineage and version, selected section, assignment or reference IDs, and unsaved editor selection only when explicitly supplied. The server verifies every anchor belongs to the authorized site. Load current publication doctrine and section overlay plus the effective editorial policy pack through existing Papyrus operations, retaining context hashes/source revisions privately. The knowledgeQuery path provides bounded evidence packs; accepted Reference policy remains the evidence gate. A missing/denied/conflicting required pack stops that tool action. Client route hints and retrieved content are context, never grants or instructions that can enlarge authority.

Keep authorization at the execution sink. Adapt existing CLI/GraphQL business operations, with an allowlist of typed tools and schemas, required permission, side-effect class and approval rule. Start with current item/reference reads and editorial check, then version save, stage transition and job start; M4 remains incomplete until the full requested inventory is mapped. Do not expose a general shell or unrestricted `execute_tactus` as the authorization mechanism. Registered skills/procedures can run only through reviewed operations and their tool registry; loading a skill grants no permissions.

For long work, propose a durable, short-lived, audience-bound job grant containing actor, Account/site, allowed operation/targets, permission version, expiry and request ID. Recheck current authority on submission and before a consequential commit. Retain service IAM for infrastructure access, but service possession of IAM is not editor authorization. Raw Cognito refresh tokens never enter chat transcripts, queues or tool events. If authority cannot be refreshed after expiry/revocation, park for editor reauthentication; the worker must not fall back to IAM or guest authoring. The exact revocation/refresh mechanism needs design review because current procedure-runner uses its own role.

Publish, unpublish, delete and send require explicit approval in the pane, bound to actor, exact tool call/arguments, target revision, scope, expiry and one-use idempotency key. A changed draft or arguments invalidate approval. Record requested, approved/denied, executing and terminal results durably; replay must not repeat a side effect. Papyrus owns the policy and backend enforcement; shared chat owns the wait/resume envelope and display state. Existing review requests may present business review tasks, but they must not be assumed to implement single-use tool approval without verification.

## Streaming, sessions and background jobs

Use POST for admission with a stable request key across retries; return channel/turn IDs. Observe one turn through GET SSE with Last-Event-ID and bounded reconnect. Persist events before exposing them; use monotonic sequence IDs and duplicate suppression. Reconcile terminal state and committed messages when streams expire or end ambiguously. Never treat a partial streamed answer as the durable transcript. The server keeps working after the pane closes; closing an observer is not cancellation.

Keep one canonical private chat transcript and durable session journal in the shared core's storage namespace. Papyrus content Message records for research packets and canonical notes remain their own domain objects. If a chat result becomes a durable newsroom note, create it explicitly with provenance; do not make every token or conversation turn searchable editorial knowledge. Papyrus may keep references/indexes to shared chat, not a second writable transcript engine.

Background contract: `startJob(operation, target, revision, input, requestKey)` returns `{jobId, status, resultRef}`; `getJob(jobId)` returns a durable state/progress snapshot and eventual result/error. Cancellation is offered only where the backend actually supports it. Job records carry actor/scope, turn/tool-call IDs and audit linkage. The short chat turn can acknowledge the job and finish. A trusted completion event records a deduplicated continuation, or the next reload reads job state. Recheck authorization before returning private results or taking follow-up actions. A long job does not keep the original SSE stream open indefinitely, and a queued job is never implemented by starting a computer. The event callback bridge and grant enforcement are proposals, not existing generic capabilities.

## Styling, accessibility and compatibility

Move relative imports and app-level `@/` dependencies behind package-local modules. Make assistant-ui a documented dependency/peer contract with a tested version range. React/ReactDOM remain peers compatible with the consumers' supported versions. Prefer a small scoped component stylesheet with CSS custom properties; adapt Papyrus typography/spacing to those variables. Do not import Chatticus's page reset or replace the newspaper shell's theme. Preserve the root export map used by the private Chattic.us-web consumer; adding a new chat entry point need not break its existing UI kit imports.

The shared surface owns keyboard composer behavior, accessible labels, transcript semantics and restrained live announcements. Papyrus owns dialog/pane naming, focus entry/return, Escape behavior and resize/dock interactions. Verify reduced motion, long messages, tool results, code blocks, contrast, narrow layout and screen-reader output; a library choice alone is not evidence these pass. Namespace state by authenticated editor/site and clear in-memory state on sign-out or site change. Two windows observe the same canonical channel without double-send or duplicate jobs.

Version the client, React surface and server core with a documented protocol compatibility matrix. Pin exact tested releases in Papyrus and its lockfiles; sites continue consuming their exact Papyrus engine pin. Publish changelogs and test actual packed artifacts in minimal consumers, including exports/CSS/types and a production build. Use one canonical machine-readable wire schema and conformance fixtures across languages. Prefer coordinated upgrades and explicit migrations over permanent dual readers, matching both repositories' rules.

## Phased work and dependency order

These are proposed slices to add beneath the existing epics after review; no production implementation is authorized by this plan.

| Phase | Owner / affected paths | Exit gate and dependency |
| --- | --- | --- |
| M1, PPY-eeb023 | Papyrus planning doc; Chatticus code/feature inventory; contract fixtures designed in Chatticus | Accept ownership, TypeScript server-hosting boundary, private transcript model, tool/job grant and wire contract. Link a real Chatticus M2 work item. Do not mark M1 closed merely for producing this draft. |
| M2a, PPY-a438d0 | Chatticus `web/lib/{sse*,resumable-turn-stream,assistant-ui-bridge,committed-activity,turn-activity}`, assistant-ui surface and new package manifests/exports | External minimal React consumer can render committed/streaming/error activity using fake transport. Existing Chatticus and private marketing export consumer remain compatible. No Papyrus-specific imports. |
| M2b later, PPY-a438d0 | Chatticus server core, storage/queue bindings, auth/policy seams, `features/` conformance; existing TypeScript Pi Durable core extraction | Chatticus consumes its own extracted core; no computer capability installed for embed profile; crash/replay/approval fixtures pass. Depends on accepted server-hosting and Papyrus backend-policy boundary. |
| M3 shell, PPY-7962e3 | Papyrus root newsroom pane and client/auth bridge | Can proceed after M2a with fixtures; rollout/loading remain with their owners. Real editor work waits for M2b and scoped backend gateway. Signed-out users get no pane or private transcript access. |
| M4, PPY-ce758e | Papyrus operation adapters, auth gateway, context packs and approval enforcement | Read/check vertical slice first; expand coverage from operation inventory. Every call is no more privileged than the editor. Depends on M1 authority contract; full pane acceptance depends on M2b. |
| M5, PPY-34b042 | Papyrus registered skills/procedures, ProcedureRun/Assignment adapter and completion bridge | One long job completes across browser closure, with one execution and an authorized result. Depends on M4 grant and shared durable continuation contract. |
| M6, PPY-839cf7 | Console/Slack transport adapters, transcript migration, retirement of responder/model-loop code | Pilot passes full acceptance; migrate existing threads with explicit ownership; drain old turns; switch one authoritative writer; remove independent Rust engine and duplicate chat-state code. Depends on all runtime/tool/job gates. |

Chatticus work affects its product repo, not the private marketing repo's billing/auth. Papyrus engine integrates dependencies; site repos receive ordinary later pin bumps, not changes in this planning task. Auritus is a boundary check for a second computer-free consumer, not a reason to implement its adapter now.

## Migration and rollback

First inventory existing chat thread ownership and Slack routing; the schema does not guarantee per-editor ownership today. Ambiguous historic threads must be explicitly assigned or held in restricted archival access, not guessed from email labels. Export and validate transcript counts/order/parent links and attachment hashes with a one-time migration. Map legacy thread IDs to shared channel IDs in a migration manifest; preserve provenance without adopting legacy schema fallbacks in the new runtime.

Trial with synthetic fixtures and an isolated pilot. For each cutover cohort, stop old admission, drain or explicitly settle old pending/running turns, migrate and validate, then enable only the shared writer. Never run both model engines on one user prompt or dual-write authoritative transcripts. Retain an immutable recovery export for rollback, not a permanent compatibility reader. Rollback before admitting new writes can restore the old lane; after new writes, freeze admission and reconcile/export new records before any reverse migration. Package rollback alone cannot safely undo transcript format or permission changes. Slack stays on its old route until its own identity/permission and reply-delivery migration is proven; the legacy engine is not retired while it still serves Slack.

## Risks, tests and acceptance

| Risk | Required verification before real rollout |
| --- | --- |
| Runtime mismatch / false extraction estimate | Update stale PyAgents/PyDurable wording on PPY-de11ec. Scope existing TypeScript core extraction separately from UI/client extraction. Verify the Papyrus host boundary and run real Pi Durable recovery fixtures, not only mocks. |
| Service role exceeds editor authority | Gherkin: editor cannot invoke admin/delete/publish sink without its required authority; forged Account/site/editor IDs, revoked membership and expired grants are refused; IAM transport grants no extra application rights. |
| Editor-to-editor or cross-site leakage | Gherkin against transcript listing, turn lookup, event listing, SSE, replay cursor, job result and attachment access. Same Account with another editor must still fail the private-channel checks. |
| Replay repeats a mutation | Crash before/after queue publish, claim, tool start, backend commit and final answer; duplicate POST, duplicate job callback and two tabs yield one canonical admission/action/result. Uncertain commit reconciles before retry. |
| Approval becomes stale or transferable | Deny/approve/resume/reload, changed item revision or arguments, another editor, replay, expiry and revocation. No action executes without its exact current approval. |
| Lost or misleading progress | Disconnect/reconnect, repeated event ID, SSE lifetime cap, expired event TTL, terminal synthesis, partial token state and reload. Final UI matches committed transcript; observer loss does not stop the worker. |
| Job exceeds turn lifetime | Close browser before completion; reopen and see job state/result. Backend failure/timeout is terminal and visible. Duplicate completion does not run the model/tool twice. |
| Context or policy leak | Synthetic policy fixtures only; private packs absent from public docs/logs/events. Missing/conflicting policy prevents the affected action. Invalid anchors and unaccepted references do not become authorized evidence. |
| Styling/package breakage | Packed package consumer build, type checks, supported React/Next combinations, current Chatticus surface and existing export consumer. No global reset bleed into Papyrus. |
| Pane excludes users with disabilities | Keyboard-only send/retry/approve/dock/close; focus restored correctly, restrained screen-reader announcements, contrast/reduced-motion and long-content tests. |
| Migration loses messages or ownership | Dry-run inventory, counts/checksums, attachment access, deterministic ID mapping, old-turn drain and recovery rehearsal. Ambiguous ownership stops migration. |

Write observable Gherkin before future behavior changes. Chatticus scenarios belong in its feature narrative and cucumber feature list; Papyrus uses frontend/backend feature suites. Use unit tests only for parsers, reducers and pure transforms. Run the changed repository's type/lint/build and relevant feature suites, then a staging end-to-end flow through real identity → turn API → job/tool authorization → storage → SSE → reload. No live model or cloud test was run for this planning task.

The first usable slice is accepted when a signed-in editor can open the pane, load only their site's private history, ask for a selected draft's editorial check, observe progress, close/reopen the browser and get the same committed result. A consequential follow-up must pause for exact approval and execute once with current permissions. The complete initiative additionally requires every approved backend capability mapped, procedures/skills supported, console and Slack migrated, and Papyrus's independent engine removed.

## Decisions requiring review

1. Accept immediate UI/client extraction and later reuse of the existing TypeScript Pi Durable core. Reconcile stale Python issue wording and Papyrus's Python-first backend policy by defining the shared server's host boundary; no Python rewrite is required for UI reuse.
2. Accept per-editor/site channels and a site-hosted shared core as the initial isolation/deployment model; define whether any admin support access to another editor's history is allowed.
3. Approve the narrow durable job-grant/revocation design and the exact consequential-action policy. Existing service IAM is insufficient evidence for editor delegation.
4. Choose in-page dock/pop-out first or a separate browser window, and agree who owns migration of ambiguous historic threads and Slack identities.

## Planning record and delivery status

No production code, shared checkout, deployment, package publication, credentials or cloud resources were changed. Isolated source copies, planning artifacts and local test scaffolding were created. The user then requested planning be filed and pushed for a Mac agent to implement. Planning branches carry the plan, Archify illustrations and Kanbus handoff records. No initiative or implementation story is marked complete. No merge, deployment or registry publication is authorized by this handoff. See the [handoff instructions](architecture/chatticus-chat/handoff.md).

Initial sandboxed Chrome and git fetch attempts failed before useful inspection/network access. The same authorized local browser verification and isolated fetch succeeded with executor escalation; no approval denial remains. All five Archify finalization receipts pass. Product code/tests/deployed state have not been changed or certified.
