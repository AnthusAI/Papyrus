# Resume the approved chat plan on the Mac

The user requested this planning handoff be filed and pushed, with implementation paused. No production code changed. Planning branches are not a release and must not be merged or deployed by inference.

1. Read `docs/chatticus-chat-integration-plan.md`, current AGENTS.md in both repositories, and PPY-de11ec / PPY-eeb023 / PPY-a438d0 / PPY-7962e3 / PPY-61ee23.
2. Read Chatticus `docs/papyrus-chat-integration-handoff.md` on branch `docs/chatticus-080b0e-papyrus-chat-handoff`, including its open chatticus-abde29 / chatticus-080b0e planning records. That branch deliberately does not push develop or start deployments.
3. Extract Chatticus HTTP/SSE client/replay behavior and React presentation into dependencies; retain product-specific login, roster, cost and computer adapters. Test a standalone consumer and make Chatticus consume the same packages. Then integrate Papyrus's console adapter.
4. Do not block UI reuse on Python migration. The inspected server uses TypeScript Pi Durable 1.0.2 and the user clarified the earlier Python terminology. Later server extraction reuses that implementation; resolve its host boundary with Papyrus's Python-first backend policy before adding a Node host there.
5. Start with executable Gherkin and a failing spec, then production code. Local-only exploratory test scaffolding from the paused session is not included and is not evidence of a completed implementation.
6. Coordinate before changing `components/papyrus-console-shell.tsx` or shared shell composition. The other M1 task owns loading states, overview Notification Center focus/removal of Go to, and mobile navigation alignment; do not alter those surfaces in the chat slice.
7. Keep per-editor/site transcript privacy, delegated permissions, exact-action approval, background job durability, migration and Slack retirement as separate gates. Do not claim the whole initiative complete when only UI is reused.

The five diagrams are standalone Archify HTML with matching typed candidates. Open the HTML after checkout; their native viewer provides theme and image/SVG export. Regenerate via the installed Archify skill, using `finalize` and the correct source repo for current-architecture evidence. `deliver ... --open` is the supported local opener; this installed CLI does not accept `finalize --open`.

No registry publication, production deployment, credential or security-access change is authorized by this handoff. Pushing these documentation branches does not publish a package or deploy an application.
