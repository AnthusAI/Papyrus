# Knowledge workstation run

The weekly run that turns a site's published items into the [knowledge snapshot](knowledge-snapshot.md) and, later, the [public wiki](public-wiki.md). Everything heavy runs on a workstation; the site backend only receives small rows. Status: Beta. Initiative PPY-428252, story PPY-9abb98.

The same run also exists as an unattended weekly job in AWS: see [knowledge-cloud-run.md](knowledge-cloud-run.md). Use the commands below for a one-off run, a fix-up or a publication that has no cloud job yet.

Shipped (`https://shipped.anth.us`) is the worked example. Replace the Shipped ids with your own site's; every command that talks to a backend names it on purpose with `--auth iam --amplify-outputs FILE`, and prints the AppSync host on stderr before it does anything.

## What you need

- A Python 3.12 virtual environment with Papyrus and Biblicus from the same release line:

  ```bash
  python3.12 -m venv venv && source venv/bin/activate
  pip install -e '/path/to/Papyrus[markus]' -e '/path/to/Biblicus[topic-modeling]'
  ```

  `topic-modeling` brings BERTopic. Papyrus already depends on Biblicus, so a released `papyrus-newsroom` pulls the base package; the extra is what a run adds. The entity step needs no model on the workstation: it asks Jev, with the key in `TYPESAFE_API_KEY`.
- The Hugging Face cache (`~/.cache/huggingface`). The first run downloads `sentence-transformers/all-MiniLM-L6-v2` (the BERTopic embedder). Later runs reuse it; `HF_HUB_OFFLINE=1` makes a run fail instead of reaching out. Keep more than 5 GB free.
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
    analysis/entity-decisions/cache.jsonl   Jev's answers, one line per name (step 8)
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
papyrus knowledge topic-config --out $RUN/topic-modeling.yml --stop-words ~/knowledge/shipped/stop-words.txt   # the settings below
biblicus analyze topics --corpus corpus --configuration $RUN/topic-modeling.yml \
  --extraction-snapshot pipeline:$EXTRACTION > $RUN/topics.json
CURRENT=$(python -c "import json;print(json.load(open('$RUN/topics.json'))['snapshot']['snapshot_id'])")
```

The settings, fixed for a small corpus (tens to a few hundred items). Do not tune them toward tidier-looking clusters from one run to the next, because the cluster identity of the next run is matched against this one; change them only on purpose, and record the change here and in the run notes.

`topic-config` writes the file below; keep the generated file and the stop-word file under version control with the run. Spelled out (the `stop_words` list is shortened here):

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
    stop_words: [a, about, above, ..., card, date, models, weights, hugging, face, 00, 01, ..., 9999, aa, ab, ...]
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

**Readable top terms.** c-TF-IDF over raw words picked `card`, `model`, `20`, `35`, `f1`, `plus` and `date` as cluster terms. The vectorizer therefore drops English stop words, the publication's own extra stop words, tokens that are pure numbers and tokens shorter than three characters. The extra words are a plain file for the publication, passed with `--stop-words` and never written into code: words separated by white space or lines, `#` starts a comment, a phrase counts as its words (the vectorizer compares single tokens). Shipped's `~/knowledge/shipped/stop-words.txt`:

```text
# words every model card repeats
card model models date weights hugging face
# fragments that read as terms
f1 plus
```

Biblicus's `vectorizer` block accepts only `ngram_range` and `stop_words` (`english` or a list of strings) and refuses any other key, and `english` cannot be combined with extra words. So `topic-config` writes the whole rule as one explicit list: scikit-learn's English stop words, the extra words, every one- and two-character token (`[a-z0-9]`) and every whole number from 0 to 9999. A number above 9999 or a fragment like `f1` that is not a whole number still needs the extra file. The list needs scikit-learn, which `biblicus[topic-modeling]` installs. **What Biblicus is missing** to do this properly: `TopicModelingVectorizerConfig` has no `token_pattern` (for example `(?u)\b[^\W\d_]{3,}\b`, letters only and at least three of them), no `min_df`/`max_df` and no `stop_words` that adds to `english`. With a `token_pattern` the config would stay a few lines and cover every number; Papyrus's list is the workaround until then. The vectorizer changes only the words a cluster is labelled with: clusters come from the embeddings and topic identity matches clusters by the overlap of their member items, so changing the stop words does not move cluster membership or `uid`s. Record a change to the stop-word file in the run notes all the same.

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

The entity step resolves a mention to an entity that is already accepted, so import the front-matter entities first. Always a dry run before `--apply`, and read the plan.

```bash
papyrus knowledge publish-run --auth iam --amplify-outputs $OUT --corpus-key shipped --actor-name "Shipped research agent"
aws sts get-caller-identity --profile papyrus-production --query Account --output text      # 712236451410
papyrus knowledge publish-run --auth iam --amplify-outputs $OUT --corpus-key shipped --actor-name "Shipped research agent" --apply
```

Front-matter entities of published items are entered by an AI research agent, so they are recorded as accepted by `ai`; `--actor-name` names that agent. Then write the registry of accepted entities for the extractor:

```bash
papyrus knowledge entities registry --auth iam --amplify-outputs $OUT --out $RUN/registry.json --vocabulary $RUN/vocabulary.yml
```

Each entry is `{key, kind, aliases}`, and `aliases` holds the node's display name and every alias it has, so name variants such as `Mistral` and `Mistral AI` resolve to the same entity when the node holds both (a `rename` keeps the old name as an alias). An alias that belongs to two entities is refused by the extractor, so the command leaves it out of all of them and prints a warning on stderr; read the warnings, and fix the entities if one of them is a duplicate. `--vocabulary` (the file of step 8; write it before this step) makes each `kind` the vocabulary's own key and leaves out, with a warning, an entity whose kind the vocabulary lacks; without it the kind is the underscore form (`model_family`) of whatever the node stores. Nodes are not rewritten. When the extractor keeps proposing a name you rejected as a duplicate (`Mistral` next to `Mistral AI`), make it an alias of the accepted entity and rebuild the registry: `papyrus knowledge entities alias --auth iam --amplify-outputs $OUT --key maker--mistral-ai --add Mistral --actor ai`.

### 8. Typed entities

The vocabulary is closed and belongs to the publication. Shipped's, as an example (`label` is the only instruction Jev gets for a kind, so keep it short; the step reads `entity_kinds` only, and `relation_types` are for the relations people and the review add):

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
  - {key: member_of, label: member of}
  - {key: licensed_under, label: licensed under}
```

`model` and `model_family` are two kinds. A model is one specific named model or checkpoint (`CosyVoice2`, `CosyVoice 3`) and shows as "Model" on entity chips and wiki pages; a model family is the line above it (`CosyVoice`) and shows as "Model Family". Neither is folded into the other. `member_of` ties a model to its family and is seeded in `corpora/papyrus-semantic-relation-types.yml` (ontology, node to node, not transitive). A reviewer accepts it only when the text states the membership; a model whose family nothing established stays without the relation. `successor_of` between two models is a separate relation and is kept as it is.

```bash
papyrus knowledge extract-entities --corpus corpus --vocabulary $RUN/vocabulary.yml --registry $RUN/registry.json \
  --extraction-snapshot pipeline:$EXTRACTION --out $RUN/typed --usage-out $RUN/typed-usage.json
```

The step is in two parts. A plain text pass, with no model, finds candidate names in the extracted texts: capitalised sequences, mixed-case and versioned names (`GPT-4`, `memoryFoo`), and lower-case words and phrases that appear in two documents or three times. It does not read reference lists (from a `References` or `Bibliography` heading to the next heading of the same or a higher level), cuts a citation number stuck to a name (`LiRA27` is `LiRA`; a version such as `Qwen3` that repeats stays), keeps a name with an apostrophe before a capital whole (`O'Connell`), skips a name whose every mention is the whole of a section heading at any level (a document's title, `Materials and Methods`: a heading that lists names counts each part), skips dates, bare numbers and quantities (`October 22 and 23`, `Hz and 10`, `3.5`: every word a number, a month or weekday, a connector or an SI unit, with at least one number), and never joins names across `and` (`Facebook and Instagram` is two names). The one exception is a single proper name that contains `and`: a connector (`of`, `for`, `on`, `in`) before the `and`, and exactly one capitalised word after it, as in `Center for Democracy and Technology`. Then Jev answers three questions per distinct name in one request, not per mention, as the name is used in up to three passages taken from different documents: is it a real, specific thing (`real`, yes or no); which of the vocabulary's kinds is it (`kind`, a `choice`); and would a reader of the publication look it up, so that it deserves a wiki page of its own (`page`, yes or no). A name Jev does not call real (probability below 0.5, the boundary of the yes/no answer) is left out. Every mention of a real name becomes a `proposed` entity with the kind Jev chose and Jev's confidence that the name is real as its `score`; nothing is cut off by that confidence, because the import's candidate filter and the AI review decide what stays. The page answer travels on the entity as `page_score` and `page_answer` (true from 0.5), both 0 and false for a name in only one document outside the reference lists, which the extractor decides itself and does not ask in the prompt; `page_documents` carries the number of documents the name is in (null on a resolved entity). `publish-run` keeps them on the concept and the wiki gives pages by them: [page answer](knowledge-snapshot.md#page-answer). The extractor's kinds come from the vocabulary's `entity_kinds`: a kind with `what` (and optionally `not_for`) is described to Jev by both, one with only a `label` by the label. The publication is described by the vocabulary's `description` (for example `a publication about gardening`), followed by `, building a wiki of concepts`; without a `description` the publication's key is used. A mention of a name the registry holds (compared with case, punctuation and spacing ignored; a one-word name must match its case, so `Go` never takes `go`) is a `resolved` entity with its `entity_key` and null page fields, and Jev is not asked about it.

Jev proposes no relations, so `relations` is empty; relations come from the front-matter import, the reviewers and the monitor records. The key is read from `TYPESAFE_API_KEY`. Answers are cached in `corpus/analysis/entity-decisions/cache.jsonl`, keyed by the name, its passages, the text of the three questions (the vocabulary's kinds included), the publication's description and the model, so a repeat on the same texts asks nothing and a changed text asks only about the names whose passages changed. `--usage-out` lists the calls that were paid for (the cloud run reads it for the stage's cost). If Jev leaves any name unanswered the command fails, writes no `output.json` and keeps the answers it has, so running it again pays only for the rest. `--extraction-snapshot` is given as `pipeline:<id>`; `--out` holds `output.json`.

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
papyrus knowledge entities alias    --auth iam --amplify-outputs $OUT --key maker--mistral-ai --add "Mistral" --actor ai   # a rejected duplicate name becomes an alias; re-run step 7's registry
papyrus knowledge entities retype   --auth iam --amplify-outputs $OUT --key platform--swe-bench --kind benchmark --actor ai   # wrong kind: add --dry-run first

papyrus knowledge clusters list     --auth iam --amplify-outputs $OUT --status all
papyrus knowledge clusters accept   --auth iam --amplify-outputs $OUT --uid cl-... --name "Short plain name" --actor ai
papyrus knowledge clusters name     --auth iam --amplify-outputs $OUT --uid cl-... --name "Better name" --actor ai
papyrus knowledge clusters reject   --auth iam --amplify-outputs $OUT --uid cl-... --actor ai

papyrus knowledge relations list    --auth iam --amplify-outputs $OUT --state proposed
papyrus knowledge relations accept  --auth iam --amplify-outputs $OUT --id ... --actor ai
papyrus knowledge relations reject  --auth iam --amplify-outputs $OUT --id ... --actor ai
```

Each command reads the whole entity table, so a long review is faster in one Python process that calls the same functions (`papyrus_content.knowledge_snapshot.entity_review`, `cluster_review`, `relation_review`, then `apply_record_changes`); it records the same fields.

`retype` is how the reviewer fixes a wrong kind. The kind is part of the key, so the entity moves to a new key (`platform--swe-bench` becomes `benchmark--swe-bench`): a new node with the same name, aliases, description and acceptance, the old node superseded, and every item link and relation moved to the new node with its metadata, so confirmed links stay confirmed. The kind must be one of the vocabulary's if the entity is to be matched by the extractor next week. Re-run step 7's registry command afterwards, then `snapshot` and `wiki sync`; anything that used the old key (a wiki page, a link) needs the new one. Details: [knowledge-snapshot.md](knowledge-snapshot.md).

Name a cluster from its top terms and the titles of its members, short and plain. Leave a cluster unaccepted when its members do not share a subject. After accepting entities, repeat step 9 (`--apply`) to import the relations that were waiting.

### 12. Snapshot

```bash
export PAPYRUS_EDGE_DISTRIBUTION_ID=EUQZ249T4OKXH
MONDAY=$(python -c "import datetime as d;t=d.date.fromisoformat('$AS_OF');print(t-d.timedelta(days=t.weekday()))")
papyrus knowledge snapshot --auth iam --amplify-outputs $OUT \
  --site-bucket amplify-dkycd9pntgo6d-main-bran-sitebucket397a1860-072ufgwmonqo \
  --static-dir ~/Projects/Shipped-web/web --beats-config ~/Projects/Shipped-web/web/scoring.json \
  --entity-href '/wiki/{slug}/' --as-of $MONDAY \
  --concept-kinds task,technique,concept,model_family
curl -s https://shipped.anth.us/_data/knowledge/index.json | python -m json.tool | head -40
```

`--concept-kinds` limits the concept of the week to those kinds (Shipped features a task, technique, concept or model family, not a platform or a licence); leave it out and every kind may be chosen. Add `--reproject` only when the site's pages use the knowledge blocks (it needs `PAPYRUS_REDIRECTS_KVS_ARN`). `--reproject` warns when the `--static-dir` checkout is behind its upstream and refuses to delete the pages of published items unless you pass `--allow-deletions`. The snapshot is deterministic for the same records and `--as-of`.

### 13. Archive the week

Take this step on every run, after the snapshot. Cluster identity (which clusters are new, continued, merged or split against the last run) cannot be rebuilt later, so the week is archived while the run is current. Use the same destination and options as step 12, and the same `--as-of`.

```bash
papyrus knowledge archive --auth iam --amplify-outputs $OUT \
  --site-bucket amplify-dkycd9pntgo6d-main-bran-sitebucket397a1860-072ufgwmonqo \
  --static-dir ~/Projects/Shipped-web/web --beats-config ~/Projects/Shipped-web/web/scoring.json \
  --entity-href '/wiki/{slug}/' --as-of $MONDAY \
  --concept-kinds task,technique,concept,model_family
curl -s https://shipped.anth.us/_data/knowledge/history/index.json | python -m json.tool | head -30
```

It writes `_data/knowledge/history/<MONDAY>.json` and refreshes `history/index.json`; it never deletes a file and never re-projects pages. Running it again for the same run changes nothing. An entry is immutable: a different run of the same week is refused unless you add `--replace`, which replaces that week only. It refuses when no cluster run is published or when the latest run is dated outside the week of `--as-of`. The format is in [knowledge-snapshot.md](knowledge-snapshot.md#archive).

### 14. Wiki

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
| Typed entities | Registry of the 119 accepted entities, vocabulary above. 71 items, 2,544 mentions (406 resolved, 2,138 proposed). |
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
- Cluster top terms are dominated by words every model card repeats (`card`, `model`, `hugging`). The names came from the member titles. Step 4 now drops English stop words, numbers, short tokens and the publication's extra words (`stop-words.txt`) from the vectorizer; that changes the labels and not the clusters. Re-run with it before the next import and compare the terms.
- The extractor is noisy outside makers and named models; most `task`, `concept` and `dataset` proposals were not worth accepting. Reviewing with a short list of exact names (in one Python process, as in step 11) was practical; reviewing 1,100 nodes one command at a time is not.
- A mention should be matched to an accepted entity before it is proposed again: `Mistral` was proposed next to the accepted `Mistral AI`. Step 7's registry now carries every name and alias of each accepted entity, which avoids those duplicates.
- A mention typed `model` for a benchmark (`SWE-bench`) or `platform` for a model card used to stay unaccepted because nothing could retype it; `entities retype` (step 11) now does.

## Second run: Shipped, 2026-10-22

The second weekly run, the same day as the first, from `origin/develop` of Papyrus and Biblicus in a fresh virtual environment. Same work folder (`/private/tmp/kb-work/shipped-run-2026-10-22`, scratch files in `runs/2026-10-22`), operator IAM lane, account 712236451410.

| Step | Result |
| --- | --- |
| Export and `reindex` | 71 published items, none new since the first run. `scanned` 72, `skipped` 1: when the corpus root is the raw folder, `corpus/knowledge-run.json` is scanned and skipped (no item id). Harmless; the check is `inserted + updated` equals the exported items. |
| Topic modelling | The same settings, with `topic-config --stop-words` (9 extra words, 11,526 stop words in all). 71 documents, 4 clusters of 21, 21, 20 and 9 items, 0 outliers (the first run had 1). |
| Identity | `--previous` the first run id: 4 `continued`, 0 `new`, `merged` or `split`. The `uid`s, names and acceptance carried over. |
| Cluster top terms | Clean: no `card`, `model`, `hugging`, `face`, `plus`, `f1` or whole numbers. `apache20` and `repo` still appear as terms; they are not on the stop-word list. |
| Run import | Dry run, then `--apply`: 4 proposals updated, 192 front-matter links unchanged. |
| Registry and typed entities | Registry of 282 accepted entities. 71 items, 2,649 mentions (1,171 resolved, up from 406) and 309 relations. Import: no new nodes, 111 new proposed relations; 91 relations skipped because an endpoint is not accepted. |
| Relation review (`--actor ai`) | 39 proposed in all (the 5 left over from the first run plus 34 new): 23 accepted (a licence or maker or base model the item states), 16 rejected (wrong target kind such as a maker as base model, a weights licence that differs from the code licence, a made-by pointing at a licence or a platform, replaces or successor claims the item does not make, and the 5 that pointed at a duplicate maker). |
| Retypes | None. No accepted entity had a clearly wrong kind. |
| Wiki | `wiki sync --no-topics --apply`: 203 pending revisions beside live pages, 79 unchanged; `wiki publish --all-drafts --actor ai --apply --no-trigger`: 203 published. A second dry run plans 282 unchanged. |
| Snapshot | `--as-of 2026-10-19 --reproject`: 282 entities, 2 beats, 4 clusters, 44 trending; 30 files written, 254 unchanged; 1,029 pages projected. |

Found on this run:

- `entities registry` writes the stored `nodeKind`, which is `model-family` for a node whose kind was slugged, while the vocabulary key is `model_family`; the extractor refuses the registry ("kind model-family outside the vocabulary"). The run mapped hyphens to underscores in the registry file by hand. Fixed (PPY-9abb98): nodes now store the vocabulary key (`model_family`), the registry always writes that form and `--vocabulary FILE` maps to the vocabulary's own keys; nodes stored earlier with hyphens are matched as the same kind and are not rewritten.
- Several items state `Mistral`, `DeepSeek`, `Moonshot` or `Aleph Alpha` as the maker; those names were rejected as duplicates of the front-matter makers and are not aliases of them, so the extractor still proposes relations to the rejected node. Fixed: `entities alias --key K --add NAME --actor ai` adds the variants as aliases of the accepted makers.
- The previous-run id lives in `corpus/knowledge-run.json`; it now holds `e7631ce7...` (topic-modeling snapshot) and `31b0af6b...` (trends snapshot).

## Concept of the week and maker aliases: Shipped, 2026-10-22

- Aliases added with `entities alias --actor ai`: `Mistral` on `maker--mistral-ai`, `Moonshot` on `maker--moonshotai`, `DeepSeek` on `maker--deepseek-ai`, `Aleph Alpha` on `maker--aleph-alpha-gmbh`. Four wiki pages (the aliased makers) have pending revisions that were not applied; the next `wiki sync --no-topics --apply` and `wiki publish` carry them.
- Snapshot re-run with `--concept-kinds task,technique,concept,model_family` and `--reproject`: the concept of the week is `task--typed-decisions` (an AI-edited description already existed), with `href` `/wiki/task-typed-decisions/` returning 200 and the home rail showing "Edited by AI on 2026-10-22". `model_family` matches nodes stored as `model-family`.
- Use a current checkout of the site repository for `--static-dir`. A first `--reproject` against a checkout 23 commits behind `origin/main` deleted the 282 wiki entity pages from the site bucket (the old `projection.json` had no wiki section); re-running `--reproject` with a fresh `origin/main` worktree restored them (984 pages written, 0 deleted). `--reproject` now refuses that deletion before writing any page, and warns when the checkout is behind; pass `--allow-deletions` only when the deletions are intended.
