# References integration verification

This draft integrates the narrow quality changes from Papyrus owner commits
`8317a95a6802d258d128590bd1ebaa54c10ee1a5` and `7c8dbe6`, excluding delivery
inventory, standalone preview servers, catalogs and project records.

Completed candidates omit the obsolete staging reason while retaining raw
registration provenance. Unknown source publication dates are explicitly
separated from intake dates. Only explicit source publication/archive fields
are forwarded to metadata workers; subtitle generation receives the actual
new title. This is an offline contract improvement, not evidence of improved
live-model output or authorization for additional paid calls.

## Actual worker proof

The read-only worker implementation is Biblicus
`1b170876b9ed9518a37ec7ca8ad1ae8d1140b9ca`. Its observed `41ab4a7` checkpoint
adds board records only; source and worker documentation match the implementation
pin. Twelve actual CLI → disposable local gateway → fake-provider tests and two
focused metadata tests pass. They cover seven-call success, failure/cancellation,
token limits, source date/archive/title propagation, duplicate/year refusal and
exact selected article spans. No live source/provider request is needed.

## Full newsroom comparison

The same Python/core environment and tokenizer cache were used for both runs.
The baseline is the original PR base `d86c89b241a3569c034a3a2084e650a34b157a7e`.
No source or issue record in the original checkout was changed.

| Run | pytest passed | pytest failed | skipped | distinct failing test IDs |
| --- | ---: | ---: | ---: | ---: |
| Original base | 846 | 48 | 7 | 47 |
| Integration | 895 | 47 | 19 | 46 |

Both runs also pass 214 subtests. Pytest failure totals include an extra reported
failure not represented by a distinct JUnit test ID. All 46 current failing IDs
also fail on the baseline; there are no newly failing IDs. The full suite is
**not green**. Common failures include missing Tactus/Poetry/uv, absent local
corpus/steering fixtures, network-dependent source resolution, and existing
procedure/message/graph assertion mismatches. These are not claimed fixed.
The 12 opt-in worker tests skipped by the default run passed separately with the
explicit pinned worker environment above.

Introduced proof gaps were repaired rather than hidden: the bootstrap test uses
the integration-owned offline source fixture and URL-only input; the BFF flow
checks the delivered one-field URL contract instead of loading an excluded
standalone server. The metadata unit test mocks its checkout boundary and no
longer requires a sibling directory. Thirty focused bootstrap/HTTP/BFF/native
checks pass, including Publish-only acceptance and scope/ownership behavior.

Generated full logs, JUnit XML and the comparison manifest are retained locally
under `.papyrus-runs/newsroom-*`; no private runtime state is committed.

## Concrete dependency publication plan

The owners are composing `codex/priming-shared-release` on public Cyclotron main,
retaining Python version metadata `0.20.1`, the supported S3/core baseline,
publication modules/guarded execution, shared PrimingPanel/client exports and the
optional-explanation fix. The UI package is private and its existing `0.2.1`
manifest is not a new registry release. No npm or PyPI publication is assumed.

After owner review and explicit authorization to publish the exact shared source
to `AnthusAI/Cyclotron`, use its immutable full Git SHA for the UI dependency and
Python source, with a regenerated lock and reproducible pack check. The proposed
`ui-v0.2.2` tag must be new; `ui-v0.2.1` cannot be relabeled. Until a reviewed
remote commit exists, Papyrus's public dependency and lock remain unchanged and
this PR stays draft. No synthetic authority route is enabled in production.

The concrete local candidate is Cyclotron
`258a7a7ee3064cb5463ecc3a185c19ea1772ed03`, one commit on public main
`c09f70b33b2b96a4e4cc2acca360af47d26620a8`. The consumer independently passes
26 BFF/native/bootstrap checks against that coherent tree. Its UI pack SHA-256
is `46228c0dfbc6ac52b882fe3136d5c90c03e456d5df92bb8792fd7dcfe97d5193`;
all installed reviewed UI source bytes match (README differs). Storage-owner
review found no source regression or excluded deployment/project/credential
paths. Any owner documentation-only successor must be recorded before the final
consumer pin. The candidate remains local and is not a reachable consumer
dependency yet. Exact next action is owner publication of the reviewed
`AnthusAI/Cyclotron:codex/priming-shared-release` branch and a draft PR into main,
subject to explicit authorization. No merge, tag or hosted activation is implied.

Final documentation-corrected candidate:
`a12ba42cf4009d95cb6430479f76deadba83bced` on the same shared-release branch.
Only three documentation files changed from `258a7a7`; source, UI and pack are
unchanged, so the consumer proof above applies. The exact pending authorization
is a push of that branch to public `AnthusAI/Cyclotron` and a draft PR into
`main`; it does not include merge, tag, registry publication or activation.

### Submit-review recovery (2026-10-16)

The temporary 8930 listener was absent at diagnosis and was restored using the
existing state, without submitting the operator's review or reloading their tab.
The operational review still requires a label and explanation (priming rationale
remains optional). The panel now explains prerequisites and read-only/session
restrictions, reports pending submission, and places failures beside the affected
review. Requests have a 15-second bound and actionable network, timeout, 401, 403,
non-JSON and backend-error messages; failed drafts and stable retry IDs remain.

Targeted client and shared-panel SSR checks plus changed-file ESLint passed.
An isolated 8931 browser fixture refused the first review with HTTP503 before
engine dispatch: the alert appeared and retained label/text, then explicit retry
acknowledged the saved correction. Only that disposable catalog gained one label.
Read-only proof on 8930 still showed zero labels and accepted examples for both
accounts. Live 8930 page/assets/context/status/history returned200 and the updated
validation guidance rendered with no browser console errors. No paid calls,
dependency installs, full Next build, cache cleanup or deployment were performed.
The existing single-entry asset build completed in1.2seconds (~1.8MB output).
