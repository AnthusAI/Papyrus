# Shared chat implementation status

Updated 23 October 2026 on BlackbookM1. This supplements the reviewed
[plan and Archify illustrations](chatticus-chat-integration-plan.md).
The initiative is in progress; the first UI increment is not full integration.

## Delivered for draft review

| Review | Exact source | Scope |
| --- | --- | --- |
| [Chatticus #636](https://github.com/AnthusAI/Chatticus/pull/636) | `f94ece3f132a9b3b563f42c35dc8c74921de68de` | Shared client/replay reducers, controlled React transcript/composer, safe markdown, scoped CSS; Chatticus consumes its own exports. |
| [Papyrus #662](https://github.com/AnthusAI/Papyrus/pull/662) | `7b445844d90e26bd85d92faa33e4a51399084fd4` | Console presentation adapter, existing host actions, exact #636 archive dependency, source transpilation and explicit CI browser acceptance. |
| [Chatticus #637](https://github.com/AnthusAI/Chatticus/pull/637) | `01de9d828c8214f69e53943d20321dcdbf9bdb1e` | Shared POST admission with caller-owned idempotency key and fresh auth, used by the existing Chatticus adapter. Stacked on #636; not consumed by Papyrus yet. |

All are isolated non-deployment feature branches. None is merged, published to a
registry or deployed. #662 pins the exact source archive of #636, so it can be
built before #636 merges, but relies on that unmerged dependency remaining
available. #637 must be reviewed after #636; it does not change #662's pin.
Do not release a Papyrus package with a provisional feature pin without a separate
review of the durable dependency/release policy. Existing Chatticus UI-kit
exports remain available; no Python migration was introduced.

Local evidence: 396 Chatticus web tests, both typechecks, relevant lint and
production web build pass. Three original shared rendering/replay/auth scenarios
pass. Four admission scenarios pass after expected red states. Papyrus's two
browser scenarios (seven steps), typecheck, lint, consumer transpilation and
production build pass against its exact installed Git archive. The corrected
browser harness uses CI's installed Chromium; local Chrome can be supplied with
`PAPYRUS_CHROMIUM_PATH`. Client transport fixtures do not certify server
idempotency, editor privacy or live AWS behavior. CI results must be checked at
the exact heads above; local green is not a claim all hosted checks are terminal.

PR660's loading, Notification Center and mobile-navigation files are untouched.
A read-only three-way check against `4d9a9b0` found no conflict markers; the only
shared file is `package.json`, with separate edits. This does not certify combined
browser behavior. Preserve its changes during later integration.

## Remaining phases and safe next work

| Phase | Can proceed locally under approved implementation/testing | Gate before real use / dependency |
| --- | --- | --- |
| M2a client completeness | Admission helper (#637), packed-consumer compatibility and controlled UI/error/accessibility fixtures. | #636 is the shared source base; Papyrus must pin a reviewed subsequent commit before consuming new exports. The private marketing consumer is not certified here. |
| M2b durable core | Extract the existing TypeScript Pi Durable runner with application-owned prompt/tool/context/store/queue seams; make Chatticus consume it; test a truly computer-free profile and crash/fence/replay with local synthetic stores/Moto. | Current executor still installs product task/board/computer tools and requires computer services. No generic server package is claimed. Resolve the site-hosted TypeScript boundary against Papyrus's Python-first backend policy before wiring its server. No second Python loop. |
| M3 pane + identity/session | Test the controlled pane and host bridge with synthetic principals, keyboard/focus/reduced-motion, session changes and scoped history fixtures. | Real SSE/history needs M2b plus a server that verifies issuer/audience/expiry and derives Account/site/editor identity. Enforce private-channel owner on every list/turn/event/attachment path. Deployment/access configuration is separately gated. Coordinate placement/loading with its owners. |
| M4 editorial tools/context | Map existing operations to typed allowlisted read/check adapters, synthetic publication/section/context anchors and explicit denial/consequential-action tests. | Requires M2b tool lifecycle and server-derived identity; resolve exact approval rules, admin support visibility and context-policy ownership. Route hints are not grants; existing service IAM is not delegated editor authority. No unrestricted shell/Tactus authorization tool. |
| M5 jobs/approvals | Implement and test durable job-result callbacks, exact-action approvals, duplicate completion, expiry/revocation and close/reopen continuation using synthetic jobs. | Requires M4 scoped grants and durable pause/resume contract. Actual job credentials, access or infrastructure changes are outside this task's current consequential-action authorization. |
| M6 migration/retirement | Implement dry-run transcript inventory/mapping validation, old-turn drain and single-writer cutover fixtures; map Slack identities without sending messages. | Requires all earlier runtime/privacy/tool/job gates. Ambiguous historic ownership needs a human decision. Real migration, engine removal/cutover and deployed Slack routing wait for explicit rollout authorization and recovery rehearsal. |

The next runtime increment should isolate the actual runner dependencies before
adding a Papyrus endpoint. A separate browser-window pop-out, administrator access
to another editor's history and historical/Slack ownership remain explicit product
choices; dockable in-page hosting is the plan's initial proposal. No cloud setup,
access expansion, package publication, merge or deployment is implied by local
implementation approval. Records remain open until the relevant work lands and
its acceptance gates pass.
