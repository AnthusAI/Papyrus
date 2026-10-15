# Optional reference example priming

The URL-only UI is ready locally at `http://127.0.0.1:8901/priming` while its
temporary process is running. Enter the URL, inspect extracted values, then supply
your label and explanation. Title, source type and summary are not initial input
requirements. The arXiv paper path uses actual Papyrus/Biblicus/GROBID processing;
web summarization is explicitly blocked pending its existing worker dependencies
and bounded provider authorization. See [acceptance and runtime evidence](priming-acceptance.md).

Papyrus can embed Cyclotron's shared preview, revision, and explicit human
label/explanation controls in its References surface. `NewsroomReferencesView`
accepts an optional `priming: PrimingPanelProps` host configuration. No control is
shown without that configuration. Regular curation and operation remain available.

The domain implementation lives in `papyrus_content.priming_curation` and runs in
the customer's external transformer service. It uses the existing catalog
registration planner and `build_reference_url_text_attachment_plans` without
applying records. The research path returns an extracted source title/abstract.
The web path additionally calls the existing
`reference_generate_metadata_from_extracted_text(..., apply=False)` pipeline to
produce title/summary. It accepts explicit in-memory metadata so that an
unregistered preview need not perform a GraphQL metadata lookup.

The same `reference_item` projection can incorporate processed title/abstract
content. No new scraper, article-text filter, scholarly parser, or summarizer is
implemented. Missing extraction or metadata fails visibly; missing title/abstract
asks for clarification. Rejection opens an explicit correction loop; its reason
and corrected fields remain separate from the final human classification.

`papyrus_content.priming_http` supplies a local/customer-hosted reference service
for the language-neutral `cyclotron-transform/v1` contract. A host supplies its
authorization function and owns TLS, source/network permissions, tool/provider
budgets, and one service owner per SQLite working store. Processing interruption
is visible as a failure. Request identities are retry-safe, cancellation is
terminal, and late results are discarded. Raw source artifacts and registration
plans stay in private working state; public job responses contain only status,
clarification fields, or the complete candidate projection. Nothing in this
service applies Papyrus registration, curation, GraphQL, or S3 writes.

Final acceptance is Cyclotron's local atomic item-plus-label operation, using
its existing authenticated application transport. The host may obtain
`PrimingService.examples(...)` and pass those accepted labels as initial context
when creating a new embedded Cyclotron store. They are not operational decisions
or evaluation results. This first slice does not silently add priming to an
already-created production relevance store or change its existing source loading.

## Reproducible synthetic local preview

This preview uses the **actual References component** and **actual HTTP job
workflow**. Only Next routing, cloud auth, source download/extraction and provider
completion boundaries are substituted. The existing extraction and metadata
planning/orchestration still execute. It refuses real source URLs and makes no
paid provider or cloud-authoring calls. All displayed content is clearly
synthetic. Ryan's chosen paper/web examples remain pending.

Use the Cyclotron priming branch beside this Papyrus worktree. Install Cyclotron
web dependencies (`pip install -e '.[web]'`) and normal Papyrus dependencies. For
the new UI exports, install Cyclotron's locally packed tarball into this isolated
Papyrus checkout (no registry publication is needed):

```sh
# In the Cyclotron checkout
npm --cache /tmp/priming-npm-cache pack --pack-destination /tmp
# In the isolated Papyrus checkout
npm install --no-save --package-lock=false /tmp/cyclotron-0.2.1.tgz
node scripts/priming-preview/build.mjs /path/to/Cyclotron
PYTHONPATH=src:/path/to/Cyclotron/src python scripts/priming-preview/serve.py
```

Open `http://127.0.0.1:8798/papyrus-preview`. The synthetic transformer is on
loopback port 8797. Choose **From reference / URL**, an
`https://example.invalid/...` URL and `research` or `web`. Reject the preview with
extraction feedback, provide corrected title/abstract through clarification, then
supply independent human labels/explanations and accept. `?classifiers=one`
shows the same workflow with one output rather than two.

The automated browser verification is:

```sh
PAPYRUS_BROWSER_EXECUTABLE='/path/to/installed/Chrome' \
PAPYRUS_PRIMING_SCREENSHOT_DIR=/path/to/screenshots \
node scripts/priming-preview/verify.cjs
```

It checks both processing paths, the research correction loop, explicit labels
for two outputs, stored target/provenance and label records, one-output mobile
cancellation, and absence of browser exceptions or page overflow. Preview state
lives under `.papyrus-runs/priming-preview/`; it is private local test data.

### Synthetic LAN review

For review from another device on the same LAN, bind an explicit private address
and use separate ports and state so existing loopback previews remain untouched:

```sh
PYTHONPATH=src:/path/to/Cyclotron/src python scripts/priming-preview/serve.py \
  --host 192.168.0.199 --port 8898 --transformer-port 8897 \
  --working-dir .papyrus-runs/priming-preview-lan
```

The review URL is `http://192.168.0.199:8898/papyrus-preview`. Browser API calls
use the same relative `/graphql` origin; the transformer remains server-side on
loopback. LAN mode refuses file imports and the synthetic processor refuses real
source URLs before fetching. This server owns a separate synthetic SQLite catalog
and has no production service or credential configuration. The preview supplies
strong random request IDs on plain HTTP LAN origins, where `crypto.randomUUID`
is unavailable. The preview build resolves Radix dependencies from Cyclotron's
installed UI tooling rather than leaving browser imports unresolved.

On the review Mac, dedicated user launch service
`gui/502/com.anthus.papyrus.synthetic-priming` owns this process with KeepAlive.
Its definition and logs live in `.papyrus-runs/priming-preview-lan/`. It survives
task completion and restarts on process exit during the current login session.
No firewall, DNS, AWS or public deployment settings were changed. Browser checks
through the LAN URL verify research revision, web summary, two explicit labels,
stored provenance, and mobile cancellation; page/assets and synthetic-only
restrictions are also checked. Actual iPad Safari and Wi-Fi reachability require
confirmation on that device. The bound address must be updated if the Mac's LAN
IP changes.

## Delivery boundaries

The local preview installs the new Cyclotron source package. The currently pinned
public `ui-v0.2.1` artifact does not yet expose the new panel. Updating the public
source/package pin must follow publication approval; do not deploy this Papyrus
change with that old UI artifact. Production activation also needs an existing
authenticated host transport, configured transformer endpoint, and a deliberate
new relevance-store/version plan. No credentials, IAM, DNS, deployment, merge,
source registration, or public examples are created by this slice.

## Accepted examples to first operation

The explicit accepted-example snapshot and optional relevance-sweep bootstrap are
implemented in `papyrus_content.priming_bootstrap` and `run_decide_relevance`.
See [the acceptance flow](priming-acceptance.md) for exact host calls, local proof,
structured import paths, real-versus-synthetic evidence and remaining inputs.
