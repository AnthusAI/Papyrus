# Knowledge workstation run

The weekly run that turns a site's published items into the [knowledge snapshot](knowledge-snapshot.md) and, later, the [public wiki](public-wiki.md). Everything heavy runs on a workstation; the site backend only receives small rows. Status: Beta. Initiative PPY-428252, story PPY-9abb98.

Shipped (`https://shipped.anth.us`) is the worked example. Replace the Shipped ids with your own site's; every command that talks to a backend names it on purpose with `--auth iam --amplify-outputs FILE`, and prints the AppSync host on stderr before it does anything.

## What you need

- A Python 3.12 virtual environment with Papyrus and Biblicus from the same release line:

  ```bash
  python3.12 -m venv venv && source venv/bin/activate
  pip install -e '/path/to/Papyrus[markus]' -e '/path/to/Biblicus[typed-extraction,topic-modeling]'
  ```

  `typed-extraction` brings GLiNER2 (PyTorch and Transformers); `topic-modeling` brings BERTopic. Papyrus already depends on Biblicus, so a released `papyrus-newsroom` pulls the base package; the extras are what a run adds.
- The Hugging Face cache (`~/.cache/huggingface`). The first run downloads `fastino/gliner2-base-v1` (the extractor) and `sentence-transformers/all-MiniLM-L6-v2` (the BERTopic embedder). Later runs reuse them; `HF_HUB_OFFLINE=1` makes a run fail instead of reaching out. Keep more than 5 GB free.
- The backend's `amplify_outputs.json` (gitignored; never commit it) and AWS credentials for the operator (IAM) lane. Papyrus does not use a person's login for this:

  ```bash
  cd ~/Projects/Shipped-web
  eval "$(aws configure export-credentials --profile papyrus-production --format env)"
  AWS_REGION=us-east-1 npx --yes @aws-amplify/backend-cli generate outputs --app-id dkycd9pntgo6d --branch main
  ```

  Before every batch of writes, check the account: `aws sts get-caller-identity --profile papyrus-production --query Account --output text` must print `712236451410` for Shipped. The credentials from `export-credentials` last about an hour; run the `eval` again when a command says they expired.

## Layout and the previous run id

One long-lived Biblicus corpus per site, one scratch folder per run:

```text
~/knowledge/shipped/
  corpus/                          the Biblicus corpus, kept between runs
    raw/papyrus/<item id>.md       written by `corpus export`
    knowledge-run.json             the previous run id (see below)
    analysis/topic-modeling/<id>/  one folder per run
    analysis/topic-identity/<id>/output.json
    analysis/topic-governance/<id>/output.json
    analysis/typed-entities/...
  runs/2026-10-26/                 vocabulary.yml, registry.json, topic-modeling.yml, logs
```

Topic identity needs the previous run's topic-modeling snapshot id, and that run must already have been identified. The id lives in `corpus/knowledge-run.json`:

```json
{"previousRunId": "10af8d00...", "runOn": "2026-10-22", "trendsSnapshotId": "193da65c..."}
```

Read it before the run (step 4) and write it again after `publish-run --apply` has succeeded (step 10). A run that failed before that step leaves the file alone, so the next run is compared with the last run that was imported. The first run has no file and no `--previous`.

## The weekly commands

Set these once per shell. `AS_OF` is the day the run is for (the trends series ends in its ISO week); the snapshot's `--as-of` is the Monday of the same week.

```bash
cd ~/knowledge/shipped
export AWS_REGION=us-east-1 HF_HUB_OFFLINE=1
OUT=~/Projects/Shipped-web/amplify_outputs.json
AS_OF=$(date -u +%F)
RUN=runs/$AS_OF; mkdir -p $RUN
ACTOR='--actor ai'
```

### 1. Export the published items

```bash
papyrus knowledge corpus export --out corpus/raw/papyrus \
  --auth iam --amplify-outputs $OUT --static-dir ~/Projects/Shipped-web/web
```

One Markdown file per published item of type `article` and `page` (`--types article,page,...` to change it; `wiki_page` is never exported by default, so entity pages do not feed their own analysis). The front matter:

| Field | Meaning |
| --- | --- |
| `biblicus.id` | A UUID derived from the item id. Biblicus keeps an id only when it is a UUID, and Papyrus item ids are not. `publish-run` turns it back into the item id, so the cluster members and extracted entities of a run name Papyrus items. |
| `papyrus_item_id`, `slug`, `section`, `url` | The item's identity; `url` is the canonical path as the site's projector places it (this is why `--static-dir` is passed). |
| `title` | The page title. |
| `dates.published_at` | The field Biblicus reads for publication dates. An item with no publication date has no `dates` block and is left out of trends. |
| `tags`, `entities` | From the item's front matter (`entities` as `kind` and `name` pairs). |

The body is the title as a heading, the deck, and the Markus source. Files of items that are no longer published are removed (only files that carry `papyrus_item_id`).

### 2. Ingest into the Biblicus corpus

A file has to live inside the corpus root for Biblicus to keep its id, so the export folder is inside the corpus and the catalog is rebuilt from it. (`biblicus ingest FILE` of a file outside the corpus is refused, and ingesting through the API gives the item a new random id.)

```bash
[ -d corpus/metadata ] || biblicus init corpus    # first run only
biblicus reindex --corpus corpus
```

`reindex` is idempotent: it inserts new items, updates changed ones and drops items whose file is gone. Check `scanned` equals the number of exported items and `skipped` is 0.

### 3. Build the extraction snapshot

```bash
biblicus extract build --corpus corpus --stage pass-through-text
EXTRACTION=$(python -c "import json;print(json.load(open('corpus/extracted/pipeline/latest.json'))['snapshot_id'])")
```

(The front matter is not part of the extracted text; the text is the heading, the deck and the body.)

### 4. Topic modelling (BERTopic) with fixed settings

```bash
PREVIOUS=$(python -c "import json;print(json.load(open('corpus/knowledge-run.json'))['previousRunId'])" 2>/dev/null)
cp ~/knowledge/shipped/topic-modeling.yml $RUN/topic-modeling.yml          # the file below, kept under version control with the run
biblicus analyze topics --corpus corpus --configuration $RUN/topic-modeling.yml \
  --extraction-snapshot pipeline:$EXTRACTION > $RUN/topics.json
CURRENT=$(python -c "import json;print(json.load(open('$RUN/topics.json'))['snapshot']['snapshot_id'])")
```

The settings, fixed for a small corpus (tens to a few hundred items). Do not tune them toward tidier-looking clusters from one run to the next, because the cluster identity of the next run is matched against this one; change them only on purpose, and record the change here and in the run notes.

```yaml
schema_version: 1
text_source:
  min_text_characters: 200
llm_extraction:
  enabled: false
lexical_processing:
  enabled: true
  lowercase: true
  strip_punctuation: true
  collapse_whitespace: true
bertopic_analysis:
  parameters:
    nr_topics: null            # no merging after the fact: the clusters are what HDBSCAN finds
    min_topic_size: 5
  vectorizer:
    ngram_range: [1, 2]
    stop_words: english
  umap_model:
    parameters:
      n_neighbors: 10          # the BERTopic default is 15; a small corpus needs a smaller neighbourhood
      n_components: 5
      min_dist: 0.0
      metric: cosine
      random_state: 42         # makes the layout, and so the clusters, repeatable
  hdbscan_model:
    parameters:
      min_cluster_size: 5      # a cluster is at least five items
      min_samples: 3
      metric: euclidean
      cluster_selection_method: eom
      prediction_data: true
```

No language model is used (`llm_extraction` is off and there is no representation model), so cluster labels are keywords; people read the top terms and the member titles and name the cluster in review. The embedder is BERTopic's default, `all-MiniLM-L6-v2`. After the run, record `document_count`, the number of clusters and `outlier_document_count` (topic `-1`) with the run notes; they are in the identity report (step 6).

### 5. Weekly trends

```bash
biblicus analyze topic-trends --corpus corpus --topic-modeling-snapshot $CURRENT \
  --bin weekly --weeks 26 --as-of $AS_OF > $RUN/trends.json
TRENDS=$(python -c "import json;print(json.load(open('$RUN/trends.json'))['snapshot_id'])")
```

`--as-of` is explicit so the run is repeatable. Items published before the first of the 26 weeks are not in any bin.

### 6. Topic identity

```bash
biblicus analyze topic-identity --corpus corpus --current $CURRENT --trends-snapshot $TRENDS \
  ${PREVIOUS:+--previous $PREVIOUS} --threshold 0.5 > $RUN/identity.json
```

The first run has no `--previous`. With `--previous`, clusters keep their `uid` across runs and get an event (`new`, `continued`, `merged`, `split`). The file is also at `corpus/analysis/topic-identity/$CURRENT/output.json`; the trends file is at `corpus/analysis/topic-governance/$TRENDS/output.json`.

### 7. Import the front matter, then build the registry

The typed extractor resolves a mention to an entity that is already accepted, so import the front-matter entities first. Always a dry run before `--apply`, and read the plan.

```bash
papyrus knowledge publish-run --auth iam --amplify-outputs $OUT --corpus-key shipped --actor-name "Shipped research agent"
aws sts get-caller-identity --profile papyrus-production --query Account --output text      # 712236451410
papyrus knowledge publish-run --auth iam --amplify-outputs $OUT --corpus-key shipped --actor-name "Shipped research agent" --apply
```

Front-matter entities of published items are entered by an AI research agent, so they are recorded as accepted by `ai`; `--actor-name` names that agent. Then write the registry of accepted entities (`key`, `kind`, `aliases`) for the extractor:

```bash
papyrus knowledge entities list --auth iam --amplify-outputs $OUT --status accepted --limit 100000 > $RUN/accepted.tsv
```

The columns are node key, status, kind, name and id. Turn each row into `{"key": <node key>, "kind": <kind>, "aliases": [<name>]}` in `$RUN/registry.json` (add the aliases the node has; an alias that belongs to two entities is refused by the extractor, so skip the ambiguous ones).

### 8. Typed entities

The vocabulary is closed and belongs to the publication. Shipped's, as an example (`label` is the only instruction the model gets for a kind or a relation type, so keep it short):

```yaml
version: 1
publication: shipped
entity_kinds:
  - {key: maker, label: company or developer}
  - {key: model, label: AI model}
  - {key: model_family, label: AI model family}
  - {key: task, label: task a model performs}
  - {key: technique, label: machine learning technique}
  - {key: licence, label: software licence}
  - {key: dataset, label: dataset}
  - {key: platform, label: platform or hosting service}
  - {key: concept, label: technical concept}
relation_types:
  - {key: made_by, label: made by}
  - {key: built_on, label: built on}
  - {key: measured_by, label: measured by}
  - {key: replaces, label: replaces}
  - {key: successor_of, label: successor of}
  - {key: licensed_under, label: licensed under}
```

```bash
biblicus extract typed-entities --corpus corpus --vocabulary $RUN/vocabulary.yml --registry $RUN/registry.json \
  --extraction-snapshot pipeline:$EXTRACTION --out $RUN/typed > $RUN/typed-stdout.json
```

The model runs on the CPU and takes a few minutes for a few dozen items (GLiNER2, about 2 GB of memory); its answers are cached under `corpus/analysis/typed-entities/cache`, so a repeat with the same text, vocabulary and threshold is instant. `--extraction-snapshot` must be given as `pipeline:<id>` for a pipeline snapshot. `--out` also holds `output.json`.

### 9. Import the run

```bash
papyrus knowledge publish-run --auth iam --amplify-outputs $OUT --corpus-key shipped --actor-name "Shipped research agent" \
  --identity corpus/analysis/topic-identity/$CURRENT/output.json \
  --trends corpus/analysis/topic-governance/$TRENDS/output.json \
  --entities $RUN/typed/output.json                 # dry run: read the plan
# same command with --apply, after the account check
```

Clusters become `topic_cluster` proposals (a continued cluster updates the proposal of the same `uid` and keeps its name and acceptance); extracted entities become `generated` nodes with unconfirmed `mentions` links; typed relations between two accepted entities become unconfirmed relations. A relation with an endpoint that is not accepted yet is counted (`relationsSkippedUnaccepted`) and picked up by a later `publish-run` of the same files once the entity is accepted, so after review (step 10) run the same `--apply` again. A second run with the same input plans only no-ops.

### 10. Record the run

```bash
printf '{"previousRunId": "%s", "runOn": "%s", "trendsSnapshotId": "%s"}\n' $CURRENT $AS_OF $TRENDS > corpus/knowledge-run.json
```

Do this only after step 9 was applied.

### 11. Review as the AI editor

An AI agent accepts entities, accepts and names clusters, and publishes the wiki pages for now; every command records who with `--actor ai` (people will use `--actor human --actor-name NAME` later; accepting again as a person replaces the AI record). Accept only what is clearly real, correctly typed and stated in the item text; reject junk spans; do not accept in bulk.

```bash
papyrus knowledge entities list --auth iam --amplify-outputs $OUT --status generated --counts --kind model --limit 200
papyrus knowledge entities accept   --auth iam --amplify-outputs $OUT --key model--qwen3-tts --actor ai
papyrus knowledge entities reject   --auth iam --amplify-outputs $OUT --key platform--card --actor ai
papyrus knowledge entities rename   --auth iam --amplify-outputs $OUT --key model--qwen3-tts --name "Qwen3-TTS" --actor ai
papyrus knowledge entities describe --auth iam --amplify-outputs $OUT --key model--qwen3-tts --text "..." --actor ai   # facts stated in the site's items only

papyrus knowledge clusters list     --auth iam --amplify-outputs $OUT --status all
papyrus knowledge clusters accept   --auth iam --amplify-outputs $OUT --uid cl-... --name "Short plain name" --actor ai
papyrus knowledge clusters name     --auth iam --amplify-outputs $OUT --uid cl-... --name "Better name" --actor ai
papyrus knowledge clusters reject   --auth iam --amplify-outputs $OUT --uid cl-... --actor ai

papyrus knowledge relations list    --auth iam --amplify-outputs $OUT --state proposed
papyrus knowledge relations accept  --auth iam --amplify-outputs $OUT --id ... --actor ai
papyrus knowledge relations reject  --auth iam --amplify-outputs $OUT --id ... --actor ai
```

Each command reads the whole entity table, so a long review is faster in one Python process that calls the same functions (`papyrus_content.knowledge_snapshot.entity_review`, `cluster_review`, `relation_review`, then `apply_record_changes`); it records the same fields.

Name a cluster from its top terms and the titles of its members, short and plain. Leave a cluster unaccepted when its members do not share a subject. After accepting entities, repeat step 9 (`--apply`) to import the relations that were waiting.

### 12. Snapshot

```bash
export PAPYRUS_EDGE_DISTRIBUTION_ID=EUQZ249T4OKXH
MONDAY=$(python -c "import datetime as d;t=d.date.fromisoformat('$AS_OF');print(t-d.timedelta(days=t.weekday()))")
papyrus knowledge snapshot --auth iam --amplify-outputs $OUT \
  --site-bucket amplify-dkycd9pntgo6d-main-bran-sitebucket397a1860-072ufgwmonqo \
  --static-dir ~/Projects/Shipped-web/web --beats-config ~/Projects/Shipped-web/web/scoring.json \
  --entity-href '/wiki/{slug}/' --as-of $MONDAY
curl -s https://shipped.anth.us/_data/knowledge/index.json | python -m json.tool | head -40
```

Add `--reproject` only when the site's pages use the knowledge blocks (it needs `PAPYRUS_REDIRECTS_KVS_ARN`). The snapshot is deterministic for the same records and `--as-of`.

### 13. Wiki

```bash
papyrus knowledge wiki sync --auth iam --amplify-outputs $OUT --beats-config ~/Projects/Shipped-web/web/scoring.json           # dry run: lists the pages it would create or change
papyrus knowledge wiki sync --auth iam --amplify-outputs $OUT --beats-config ~/Projects/Shipped-web/web/scoring.json --apply   # drafts only
papyrus knowledge wiki publish --auth iam --amplify-outputs $OUT --all-drafts --actor ai --apply   # the AI editor's stamp; see public-wiki.md
```

Wiki pages are ordinary published items, so the next export (step 1) skips them by type. The site must already pin a Papyrus release that has the wiki section and the knowledge blocks ([public-wiki.md](public-wiki.md)).

## First run: Shipped, 2026-10-22

The first real run, on a Mac, from `origin/develop` of Papyrus (plus this change) and Biblicus 1.15.0. Work folder: `/private/tmp/kb-work/shipped-run-2026-10-22` (corpus, outputs and logs). Operator IAM lane, AppSync host `imnmexcbrzcddk2g4vl6hsn7ie.appsync-api.us-east-1.amazonaws.com`, account 712236451410.

| Step | Result |
| --- | --- |
| Export and `reindex` | 71 published items (70 `article`, 1 `page`), 0 undated; `scanned` 71, `skipped` 0. |
| Extraction | `pass-through-text`, 71 extracted, 0 empty. |
| Topic modelling | The settings above, once, not tuned. BERTopic embedder `all-MiniLM-L6-v2` (downloaded on this run). 71 documents, **4 clusters** of 21, 20, 20 and 9 items, **1 outlier** document (topic `-1`). 13 seconds. |
| Trends | `--bin weekly --weeks 26 --as-of 2026-10-22`; 0 undated items. Many items are older than 26 weeks, so the series count fewer items than the clusters hold (cluster of 21: 5 items in the window). |
| Identity | First run, no `--previous`: events `new` 4, `continued` 0. Threshold 0.5. `document_count` 71, `outlier_document_count` 1, `cluster_count` 4. |
| Front-matter import | 119 accepted nodes (54 makers, 65 tasks) and 192 confirmed links, recorded as accepted by `ai` (actor name "Shipped research agent"). |
| Typed entities | GLiNER2 `fastino/gliner2-base-v1` (revision `f9634218`), threshold 0.7, registry of the 119 accepted entities, vocabulary above. 71 items, 2,544 mentions (406 resolved, 2,138 proposed) and 292 relations. About 3 minutes on the CPU. |
| Run import | Dry run, then `--apply`: 4 cluster proposals, 1,173 generated nodes, 1,767 unconfirmed extractor links, 1 relation (291 skipped because an endpoint was not accepted yet). |
| Entity review (AI editor, `--actor ai`) | 170 extractor entities accepted and 271 rejected as junk (sizes and file formats such as `27B`, `GGUF`; the word `card`; hardware, metrics, languages, generic nouns). 7 more were rejected afterwards because each repeats a front-matter maker under another name (`Mistral` for `Mistral AI`, `Moonshot` for `moonshotai`, ...). Net: 282 accepted, 277 rejected, 719 left `generated` (not public). Candidates the extractor typed wrongly (a benchmark typed as a model, a platform typed as a task) were left alone, not accepted. |
| Second import | The same `publish-run --apply` after the review: 89 more relations between accepted entities (90 proposed in all). Reviewed: 55 accepted (the item says it, for example "Qwen releases Qwen3Guard", "under MIT", "built on the MiniCPM-4 backbone"), 30 rejected (wrong or not stated, for example `licensed_under` Hugging Face), 5 left proposed because an endpoint was one of the duplicates rejected above. |
| Clusters | All four accepted and named by the AI editor from the top terms and member titles: `cl-e7fea314e953` "Open text-to-speech models" (21 items, all open TTS), `cl-fb1252e1da52` "Decision models" (20; 19 decision models and the Policies page), `cl-522d40c1a286` "Open-weights language models" (20), `cl-482084205aab` "Safety and guard models" (9; one item is a Nemotron reasoning model). |
| Descriptions | Ten entities described with `--actor ai`, from facts in the item titles and text only. |
| Snapshot | `--as-of 2026-10-19`, 282 entities, 2 beats, 4 clusters, 44 trending; 284 files written. Live at `https://shipped.anth.us/_data/knowledge/index.json`. |
| Wiki sync | Dry run only: 282 entity pages and 2 beat pages would be created as drafts. Not applied: Shipped needs a Papyrus pin bump first. |

The previous run id is stored at `corpus/knowledge-run.json` of the work folder: `previousRunId` `10af8d000683aa5c118b29b438a56d66eb245372bdc37004c60b437d7b2dfc7f` (the topic-modeling snapshot id), `runOn` 2026-10-22, `trendsSnapshotId` `193da65c5d1ad3e0c27071f0f67ad26b58fbed46fd7eb42f09a73dccafeef2ae`. Next week's `topic-identity --previous` takes that id. Move the work folder into `~/knowledge/shipped` (or keep using it) so the corpus and that file persist.

What the first run taught, for the next one:

- With 71 items, BERTopic with these settings found four broad clusters and almost no outliers. That is what the settings produce, not a measure of how stable the clusters will be: the identity report says every cluster is `new` because there is no earlier run. Record the smallest corpus size at which events stayed stable once there are two runs to compare.
- Cluster top terms are dominated by words every model card repeats (`card`, `model`, `hugging`). The names came from the member titles. A stop-word list for the publication would improve the terms; it would also change the clusters, so do it as a recorded change.
- The extractor is noisy outside makers and named models; most `task`, `concept` and `dataset` proposals were not worth accepting. Reviewing with a short list of exact names (in one Python process, as in step 11) was practical; reviewing 1,100 nodes one command at a time is not.
- A mention should be matched to an accepted entity before it is proposed again: `Mistral` was proposed next to the accepted `Mistral AI`. Adding the aliases of each accepted maker to the registry (step 7) avoids those duplicates.
- A mention typed `model` for a benchmark (`SWE-bench`) or `platform` for a model card stays unaccepted, and there is no command to retype it.
