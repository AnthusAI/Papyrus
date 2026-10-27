# Newsletter acceptance handoff — 2026-10-27

Implementation ownership ended at the user’s request. This branch preserves unfinished work; it is not a release candidate. Kanbus PPY-98b5e907-782c-4799-888a-79b4f63825c2 remains open.

## Actual live outcome

p.apyr.us runs 5.41.8, site PR90, merge 59e944a1fd3c67d16796b783c66bdbf49b4c8228. Workflow 40518816799 succeeded; Amplify build 87 succeeded around 14:26 UTC. Both deployed monitoring-view and content-actions artifacts were compared with the tested release source before acceptance.

Both specifically authorized forwarded newsletters arrived and their links were extracted (19 and 41 candidates). Authenticated exact-receipt access works without loading the overview. ZERO References were imported from these receipts, ZERO classification jobs were created by these tests, and ZERO votes were cast. Predictions and normal Reference review controls have not been accepted end to end.

The first receipt still showed branded SendGrid wrappers as direct links: the released recognizer supported a single path segment, while the observed wrapper has multiple segments. All selections were cleared; no resolver request was made for that receipt. Only a sanitized structural observation was retained in this repository’s synthetic tests.

The second receipt’s Read online candidate was attempted once after 5.41.8 deployed. The UI returned redirect_response_unusable. The released response does not identify HTTP status or whether failure occurred at the tracker or destination. Do not assert a 403/405, or retry without a material correction. Earlier 5.41.7 attempts of candidates 0 and 2 also failed safely. No import occurred.

## Preserved WIP

Base: engine 3711ceb9a095f936264b416ac02c003a6c1697ce (PR769, released 5.41.8). Handoff branch: handoff/PPY-98b5e9-newsletter-2026-10-27.

The unshipped correction recognizes synthetic multi-segment branded wrapper paths and adds bounded URL-free status/hop diagnostics through the resolver, API and UI. It retains HTTPS, public DNS validation and pinned transport, HEAD-only resolution, redirect limits and account-action guards. No GET fallback or newly accepted response status was added. Synthetic complete resolve-to-import-to-queue coverage includes single and multi-segment wrappers.

Before the final extra testcase edit, 162 targeted Python tests and 4 Gherkin scenarios (13 steps) passed; monitoring UI script and TypeScript typecheck passed. A final parameterized transport testcase and multi-segment unsubscribe testcase were subsequently added to test_email_submission.py and have NOT been rerun. The final focused ESLint process result was not captured. No full validation or CI has run for this final WIP. No new tests were run after the user ended implementation ownership.

The requested census of all distinct article tracking shapes across the two authorized receipts, and offline inspection for encoded clean destinations, were NOT completed. The diagnostic action did not execute because automatic approval review hit a usage limit; after usage reset the user cancelled implementation. Do not infer results from the prepared diagnostic plan.

## Cloud handoff already deployed

PR753 introduced receipt-specific UI and idempotent imported-Reference classification handoff. PR761 fixed actual Amplify event dispatch and rejects unknown/missing/conflicting names without overview fallback. PR769 normalizes legacy branded candidates at both view and intake, but has the path-shape defect above. Forward ports PR757 and PR771 reached develop; PR771 merged as c969e50801990eca7961a25ed6fc0858f37cfd83.

The selected-email router task is email-references on monitor p-apyr-us-email. Its enabled five-minute schedule is papyrus-monitoring-email-references. Optional selected source IDs are bounded to 1–20, with maxItemsPerRun 5. Import queues idempotent discoveries with provenance and no human label; selected parked records retain retry eligibility. No ordinary broad backfill is required. This path has source/tests and deployed infrastructure evidence, but no successful live job from these two receipts.

The shared router was patched from its actual deployed baseline, not replaced with the maintenance branch wholesale. Last verified CodeSha256: f3dQEBybOAw/f7YruGw7KaIURsZZZsK1iWWm+jJQqqg=. Recheck the actual baseline before any future shared change; preserve concurrent stale-job and Decision Ready dispatch work if deployed. Never assume the ordinary doorbell schedules this monitor.

## Remaining acceptance and boundaries

1. Review this WIP against current upstream and complete all authorized article wrapper shape fixtures. Establish whether a clean destination can be extracted safely without another tracking call. Do not weaken resolver security to overcome an unexplained response.
2. Finish focused tests and review before any later release. Reconcile current maintenance/package/site versions rather than reuse a published number or overwrite concurrent chat work.
3. Through normal editor authentication, open only the two authorized receipts, resolve only genuine article candidates, import selected clean destinations with dedupe/provenance, then verify bounded selected-item classification and actual review controls. Exclude unsubscribe, account actions, promotions, ratings, polls and sponsors. Existing predicates do not mechanically recognize every promotional label.
4. Verify Reference detail visibility and Needs review count/filter. PR759 on develop is a relevant lead, not a proven deployed defect in these tests. No votes are authorized; do not claim feedback training was verified.

No broad receipt overview or other submission read is authorized. The exact receipt identifiers and private evidence remain in the original task workspace, not this repository. Do not publish raw tracking URLs, receipt tokens, email addresses, screenshots containing them, or authentication material. Native CLI/Keychain login is not a newsletter feature prerequisite and must not become another test detour. No new credentials, claims, groups or grants are part of this handoff. The legacy inbound receiver switch stays unchanged.

One earlier exact-receipt request hit the old overview fallback. Recorded UI showed unavailable; original network response was not captured. No other receipt summaries/bodies appeared in recorded tool output, but actual response contents cannot be established from retained evidence. The fail-closed dispatch correction shipped in 5.41.7; do not repeat a broad request to investigate.

## Repository cleanup

Only confirmed newsletter worktrees will be removed after remote preservation is verified. Shared primary checkouts and the predecessor dependency directory papyrus-email-monitor-partition-fix are retained. The older newsletter-exact-receipt checkout has uncertain ownership and is retained rather than assumed disposable. Private checkpoint and deployment verification evidence remain in the task workspace. No implementation, release, deployment or cloud mutation is part of closeout.
