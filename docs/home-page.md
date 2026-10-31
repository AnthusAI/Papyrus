# Home page: public data files

> Status: Beta, phase 1 of the `homePage` epic (PPY-1b83d3). This page covers the data files, the fields, the task and the CLI. The Reference grids are described under "The references include"; the freshness trigger and the threads come in later tasks.

A Papyrus site can show part of its curation to visitors. The first piece is a public JSON file of the site's accepted References and of the pending ones the Cyclotron expects an editor to accept. It is served next to the pages, for example `https://anth.us/_data/home-page/references.json`.

## Data files

| File | Holds |
| --- | --- |
| `_data/home-page/references.json` | `generatedAt`, `corpus`, `fields` (the published field names) and `references`, accepted ones newest-accepted first, then recommended ones newest arrival first |

The file lives under the site's URL policy, so `urls.basePath` is honoured (`<basePath>/_data/home-page/references.json`). Reconcile never calls it an orphan.

## Which References

- **accepted**: `curationStatus` accepted and `versionState` current.
- **recommended**: pending (`<corpusId>#unrated`) and current, whose live P(accept) is at least `homePage.references.recommendedThreshold` (default 0.5, the threshold the console already uses to skip predicted rejects). P(accept) is the console's `acceptProbability`: the confidence of the current `relevance_decision_is` decision when it chose the positive label, one minus it otherwise, 0.6 when no confidence was recorded and 0.5 with no decision.
- Rejected, archived and superseded References are never exported.

## Public fields

`key` (the first 12 hex characters of the SHA-256 of the lineage id, so no id appears), `status` (`accepted` or `recommended`), `title`, `authors`, `url`, `host`, `mediaType`, `sourceDate`, `sourceUpdatedAt`, `retrievedAt`, `importedAt`, `arrivedAt`, `acceptedAt` (accepted only), `decidedAt`, `section` (the section's title), `reasonCode`, `actor` (`human`, `cyclotron`, `rule`, `agent` or `catalog`; never who), `shareable`, `confidence` (live P(accept), two decimals), `predictedAcceptProbability` (the original prediction), `predictionDecidedAt`, `inboundCitationCount`, `outboundCitationCount`, `versionNumber`, and from the preview attachment `image`, `summary` and `siteName`.

The allowlist is `PUBLIC_REFERENCE_FIELDS` in `src/papyrus_content/home_page/export.py`. `homePage.references.fields` is `"all"` (every field above, the default) or a list of those names that includes `key` and `status`; any other name is a build error.

Never published, each with its reason in `EXCLUDED_REFERENCE_FIELDS`: identity (who decided, who relayed, an editor's private note, intake provenance), the captured text of the source and its storage details, and internal ids and keys. A unit test proves every field of the Reference model is either published or excluded, exactly once, and the Gherkin scenarios scan an export with the reader-privacy scanner. `summary` is the preview's description clipped at `publicData.summaryCharacters` (default 240) on a sentence boundary. Text is also scrubbed of anything shaped like an email address, a UUID or a site subject, and a Reference whose address would carry one in its path is left out.

## Settings

The `homePage` key of `projection.json`; a site without it has no home-page behaviour. Unknown keys are a build error that names the key.

```json
{"homePage": {"layout": "latest", "perSection": 4,
  "references": {"corpus": "knowledge-corpus-example", "fields": "all", "defaultCount": 6, "recommendedThreshold": 0.5},
  "threads": {"enabled": false, "authors": "handle", "anonymousLabel": "Editor"},
  "freshness": {"debounceSeconds": 300, "intervalHours": null, "purge": false}}}
```

`references.corpus` defaults to the corpus of the site's publication key (`PAPYRUS_PUBLICATION_CORPUS_KEY` in the Lambda, `--site KEY` on the CLI).

## The task

`home-page-snapshot` runs in the content-actions function (`{"projectionTask": {"task": "home-page-snapshot"}}`). Under the projection lease it builds the document, writes the file only when its content changed (the `generatedAt` stamp alone is not a change), then re-renders only the listing pages whose inputs changed and, with `freshness.purge`, purges the file on the edge. A site without a `homePage` setting ignores the task. The report is `{written, unchanged, references, pagesRewritten, purged}`.

## The CLI

```bash
papyrus home-page snapshot --site KEY --site-bucket BUCKET --static-dir SITE/web --auth iam --amplify-outputs FILE
papyrus home-page snapshot --site KEY --out DIR          # a local directory
papyrus home-page snapshot --site KEY --dry-run          # counts and file size; writes nothing
```

Mutation commands write by default; `--dry-run` prints the report and the size of the file only. `--static-dir` points at the site checkout so its `projection.json` (including `urls.basePath`) applies; without it the defaults are used.

## The references include

`::include{kind="references" select="recent|confident|recommended" count="6" [section="Tools"] [card="tile|row"] [heading="..."] [more="/path/"] [empty="..."]}` places Reference cards on an authored page, rendered at projection time from `_data/home-page/references.json`. A site needs the `homePage` setting; without it the include is a build error that names the page file.

- `recent`: accepted, newest accepted first. `confident`: accepted, highest Cyclotron confidence first (none recorded counts as 0.5). `recommended`: not yet accepted, highest confidence first. Ties go to the newest arrival, then the key.
- `count` defaults to `homePage.references.defaultCount` (6). `section` keeps References whose section label (or a configured section name's label) matches.
- Each page has one ledger. The first component to place a Reference keeps it; a later component skips it and refills up to its `count` from its own ordering. Nothing is shared between pages.
- A card shows confidence as "93% confidence" with a Lucide `gauge` icon and a five-segment meter drawn by shape (filled or outlined). A recommended card says "Recommended by Cyclotron, not yet accepted" with a `sparkles` icon. Cards use flat tones and rounded corners, with no borders. A component with nothing left draws the `empty` text, or nothing.
- The Markdown twin keeps the include line as written. A page's digest folds in the snapshot digest, so a changed snapshot rewrites only the pages that place a references include.
- `pages[].path`, a section `base` or a collection `base` equal to `_data`, `_plugins`, `_papyrus`, `_next` or `api` is a build error. `newsroom` is also reserved on sites whose edge routes the CMS.
