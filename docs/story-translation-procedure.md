# The Story translation procedure

`papyrus.story.localize` (PPY-843a7c) translates one published Story into one language per run, checks it against the English, polishes it
until the findings stop shrinking, and saves it as an unpublished version of the Story's localization. Nothing waits for a person and the run never
publishes: the result is published by a person, or by the site's own switches for it (`--publish-clean`, translate on publish) ([Publishing a translation](#publishing-a-translation)). Plan: [multilingual publishing](plans/multilingual-publishing.md). Design notes: the procedure stages, budgets and evaluation from the
2026-11-13 design (sections 3.1 to 3.9), with Ryan's decisions of that day.

## The record model

- Every Item version has `language` (BCP 47, Humanus spelling: `en`, `es-419`, `zh-Hans`) and `languageGroupId` (the primary Story's lineage; on a tenant backend the stored row carries the tenant prefix, `machines-on-machines#{lineage}`, which readers remove with `bare_group_id` before comparing it with a lineage).
- A localization is a sibling lineage `{primaryLineageId}--{language}`. Each version names the primary version it came from
  (`sourceLineageId`, `sourceVersionNumber`, `sourceContentHash`) and has `syncState`.
- A translation has no board stage and stays out of the board and the English listings until the listing keys carry the language (plan, deploy 2).
- Its address (`slug`) is drafted once, at its first version, by the language's slug policy (`languages.slugs`: `translated` for Spanish, `characters`
  for Chinese; [serving](multilingual-serving.md#unicode-addresses)) and kept by every later version; `papyrus stories set-slug` changes it before the
  first publish. It carries the original's stored pictures (each version copies the original's media rows for the pictures its text names), so the
  publish check that every picture is present passes.
- Its provenance is a ModelAttachment on the version (role `localization_provenance`): source, models, prompt version, Humanus, language pack,
  policy pack and glossary versions, rounds, reverted blocks, findings by category and severity, cost by purpose and the prediction, outcome, the
  alignment (each block's source block, owner, pinned flag and text) and the checklist steps it proves.

## Setting a site up, and starting a run

A site needs four things before a run starts; none is an Automation, a monitor or a router publication.

1. **The language is enabled**: `languages.enabled` of the editorial check settings names it (`es-419`); it stays out of `languages.public` until the owner decides.
2. **The procedure is registered once**, under the key `SITE.story-localize` where SITE is the site's host (`newsroom.example.com.story-localize`). Register it again
   after a release that changes `procedures/newsroom/story_localize.tac` (the procedure's input is checked against the registered version):

   ```sh
   papyrus --auth iam procedures register --file procedures/newsroom/story_localize.tac --key SITE.story-localize --dry-run --json
   papyrus --auth iam procedures register --file procedures/newsroom/story_localize.tac --key SITE.story-localize
   ```
3. **The language's guidelines are saved** (by an admin, once; a translation reads only what the site saved, and a site with none translates with no glossary and no register note):
   - the starter glossary overlay, `src/papyrus_content/data/glossary/<language>.json` (for `es-419`: `AI` is `IA`, `computer` is `computadora`, Paris is París, and so on). The translator is
     told the entries that occur in each block and the faithfulness check verifies them:
     `papyrus guidelines save --kind glossary --language es-419 --file src/papyrus_content/data/glossary/es-419.json --reason "Starter glossary" --expected-current-version-id none`;
   - the language's register in a `writing` overlay (`--kind writing --language es-419`, field `tone`): which form of address the reader gets. Humanus's `word-choice-es-419` pack sets
     none (it only lists words that differ from Spain's), so the site decides; an unsaved overlay leaves the model free to pick tú or usted, call to call. Machines on Machines uses
     usted ("Lea la fuente"), the neutral form of the Latin American press.
4. **The model key** is available to the run: `OPENAI_API_KEY` in the process that starts it, or the site's SSM parameter named with `--openai-key-parameter`
   (read with the operator's AWS credentials and never printed).

`LocalizationRequest` (id `{languageGroupId}#{language}`) is the desired-state record: the newest published source version to translate. One command writes it
and starts the run:

```sh
papyrus stories localize --story LINEAGE --language es-419 --dry-run             # the plan: blocks to translate, glossary terms, predicted cost
papyrus --auth iam stories localize --story LINEAGE --language es-419 [--ceiling-usd 1] [--procedure KEY] [--openai-key-parameter SSM_PARAMETER]
papyrus stories localize --story LINEAGE --language es-419 --automation SITE.story-localize   # the site's runner starts it instead
```

- **Without `--automation`** (the way a person or an agent asks for one translation) the command runs the registered procedure in its own process through the
  procedure runner's code (`procedure_runner.run_procedure_request`, `localize/start.py`): the procedure's published version is loaded from the site, a
  ProcedureRun records its status, model usage, cost and output, and a child process executes it with every tool real, signed as the operator, so it needs
  `--auth iam`. The command waits for the run and prints the run id, status, cost and the procedure's output. A failed run exits non-zero; the same command
  again continues from its finished stages.
- **With `--automation ID`** the site's runner starts the run, as it does any procedure of a monitor automation (`docs/automations.md`), and
  `papyrus automations runs --id ID` follows it.
- `--procedure KEY` names the registered procedure when it is not `SITE.story-localize`. The procedure's earlier ProcedureRuns, found through that key (or the
  automation's `procedureKey`), give the cost prediction; a `--dry-run` with neither names no procedure and predicts from no history.

A run with no request, or for an older source than the request names, stops before any model call. The run records its outcome on the request (`saved`,
`held`, `waiting`, `failed`, `stopped`, `unchanged`; `published` once the translation is live), unless the request has moved on to a newer source meanwhile: a run
checks the request again before it saves, and a Story republished while it worked leaves the older run saving nothing (the newer request has its own run).
The procedure's inputs are snake_case (`story`, `language`, `ceiling_usd`, `source_version`, `run_key`, `automation_id`, `procedure_key`): an automation's run
accepts no other spelling ([automations](automations.md)), so register the procedure again after upgrading from a release that used camelCase.

## Translating the whole site

`papyrus stories localize --all` translates every published Story that has no up-to-date translation, in one language or all of them:

```sh
papyrus stories localize --all --language es-419 --dry-run                       # what remains, with the predicted cost; writes nothing
papyrus --auth iam stories localize --all --language es-419 --publish-clean       # run them here, publish the clean ones
papyrus --auth iam stories localize --all --all-languages [--concurrency 3] [--ceiling-usd 1] [--openai-key-parameter SSM_PARAMETER]
papyrus stories localize --all --language es-419 --automation SITE.story-localize [--publish-clean]   # queue them for the site's runner
```

- **What remains** (`localize/backfill.py`) is found without a read per Story: one paged listing of the published summaries (each has its language, its
  language group and the source text's hash) and one listing of the `LocalizationRequest` records. A Story written in the primary language (not a
  translation, not marked do not localize) has an up-to-date translation in a language when the record there names this very text and its state is
  `saved`, `held`, `unchanged` or `published`. A held translation counts: it waits for a person. A record for older text, a run that `failed`, `stopped` or
  never started (a `started` record older than an automation's longest run), and a Story with no record are remaining work. Running the command again
  does only that.
- **In this process** (the default; needs `--auth iam`) each remaining Story is requested and run through the registered procedure exactly as
  `papyrus stories localize --story` does, `--concurrency` at a time (default 3; each run mostly waits for the model). One line per Story and language:
  `saved`, `held` (a person answers its review request), `failed` (its reason; the others go on), `up to date`, `published`, `not published`, with the run's
  cost, and a totals row. The command exits non-zero when a run failed and says to run it again; a failed run continues from its finished stages. The
  cost ceiling is the one of the single command (`--ceiling-usd`) and the learned band of the language (no fixed cap).
- **`--publish-clean`** publishes through `publish_item`, the ordinary path, and builds the page: only translations whose run saved cleanly
  (`metadata.localization.outcome` is `saved`), that are not already live at that text, in a language the site writes in, and only while the original is
  still published at the very text they were translated from (`localize/publish.py`, one rule for this command and for translating on publish). A held
  translation is never published by a machine; the site's approval gate and the public-language gate apply as to any publish. It also publishes
  translations saved by an earlier run that nobody published.
- **`--dry-run`** reads the procedure's measured runs once (the procedure of `--procedure`, `--automation`, or `SITE.story-localize`) and prints each remaining
  Story's predicted cost from this language's median cost per source character; a language with no measured run has no prediction and the row says so.
- **`--automation ID`** writes the records `wanted` with the automation and the publish choice and returns; the site's dispatcher (below) starts and
  publishes them. Without the release's backend deployed nothing starts them: say so before queueing.

## Translating on publish

A site can translate every Story into every enabled language, and publish the clean results, when a Story is published or republished. It is off until the
site's `languages` setting says so (`docs/multilingual-serving.md`):

```sh
papyrus editorial languages --auto on --auto-automation SITE.story-localize       # publish: true unless --auto-publish off
papyrus editorial languages --auto-publish off                                    # save translations for a person to publish
papyrus editorial languages --auto off                                            # the automation and the publish choice stay stored
```

`languages.auto` is `{"enabled": true, "automation": "SITE.story-localize", "publish": true}`. It needs the site's translation procedure registered and an
Automation that runs it (`papyrus automations create --id SITE.story-localize --title "Translate a Story" --monitor MONITOR --publication PUBLICATION
--procedure SITE.story-localize`, [automations](automations.md); the router publication supplies the endpoint and model key), exactly as `--automation` needs.

The mechanism, once per change and without a table read per change:

1. **The publish writes the desired state.** When a Story written in the primary language is published (the one funnel every publish path ends in:
   `announce_published_story` in the content-actions function, after the page is live), `localize.auto.request_translations` writes one
   `LocalizationRequest` per enabled language other than the primary: the newest published source version, `automationId`, `publish`, state `wanted`.
   A record already naming the same text asks for nothing again (unless its run `failed` or `stopped`); a newer publish overwrites the record (coalescing). A
   translation, a Story in another language and a Story marked do not localize request nothing. A failure to write is logged
   (`papyrus_translation_request_failed`) and never fails the publish; `papyrus stories localize --all` writes what is missing.
2. **The dispatcher reacts on the site's runner.** A DynamoDB stream on `LocalizationRequest` invokes the `localization-dispatch` function
   (`amplify/functions/localization-dispatch`, deployed with the site's backend; not wired on a shared stack). It reads the waiting records through the
   `localizationRequestsByState` index (state `wanted`, oldest first, never the table), claims each with a conditional write (`wanted` to `started`) so
   overlapping batches never start one run twice, and starts it through the automation by the same code as Run now: the automation's `enabled`, timeout and
   `maxConcurrent` apply and the router's publication supplies the model key. At the limit the rest stay `wanted` and the next run to end starts them; its own
   put-back does not wake it. A record naming no automation is a person's in-process run and is left alone; one naming an automation that does not exist is
   `failed` with that reason.
3. **The run** is the registered procedure as ever (translate, check, polish, save, hold). Held translations raise their review request and wait for a
   person; nothing here clears a hold.
4. **Clean results publish.** When a record becomes `saved` and `publish` is set, the dispatcher has the content-actions function publish it (task
   `publish-localization`) through `publish_item_action`, the console's publish: `localize.publish.publishable` allows it only while the language is
   enabled, the original is still published at the text the request names, the run saved it cleanly and it is not live already. A refusal of the publish
   itself (the site's approval gate) is written on the request's `reason` and is not retried. The language's `public` setting still decides whether the
   published translation has a page.

Each record answers "where does the Spanish translation of this Story stand" (`wanted`, `started`, `saved`, `held`, `failed`, `stopped`, `published`).
After the release is deployed to a site: register the procedure again (its inputs are renamed), create the automation, then `--auto on`. Turning it on does not
translate Stories already published: run `papyrus stories localize --all --publish-clean` once.

## Stages

1. **collect**: the published primary version, the previous localization and its alignment, the glossary entries for the language and section
   (`translation_glossary`), the language's copy-edit pack, the language overlays' register notes, earlier runs' spend; the run key.
2. **budget**: the cost predicted from this language's measured runs (`localize/budget.py`: median cost per source character; Tukey's upper
   fence as the outlier band once four runs exist). A caller's ceiling makes the run wait when the prediction is above it.
3. **translate**: only the blocks whose source changed. The blocks are the title, the dek, the front matter's reader-facing texts (`blurb`, `imageAlt`: kinds `field:blurb`, `field:imageAlt`, saved back into the translation's front matter; references and picture paths stay as written) and the body's blocks. Link targets, URLs, citations, code and every directive attribute except `alt`, `caption`
   and `title` are replaced by placeholders and put back by the system, so a translator never sets a link target or a credit.
4. **normalize and parity**: emphasis that would not render is fixed by code (the punctuation moves outside the closing marker); the Humanus
   `translation-faithfulness` parity rules run on each block.
5. **bilingual judge**: GPT-6 Luna through Humanus's judge hook, two passes per block, quotes verified by code.
6. **copy edit**: the language's own policies (typography, translationese, AI-writing tells, house words, Spanish initialisms, and the formal imperative when the site's overlay chose `usted`).
7. **refine**: repairs with a certain fix (a `replacement`) are applied by code, and the model is asked only about what the repaired text still has; error-severity faithfulness findings, and findings of rules
   measured right about nine times in ten on held-out examples in that language (`evidence.precision`), go back to the model.
8. **loop**: 4 to 7 on the changed blocks while a round strictly reduces (faithfulness errors, faithfulness warnings, rewrite findings, certain
   repairs) and adds no faithfulness finding; a block whose rewrite makes faithfulness worse reverts. It ends on convergence.
9. **record**: the new unpublished version, its provenance, and the advice on the English version (`metadata.translationAdvice`) for stock phrasing
   the copy edit found in the translation that the English block has too.
10. **gate**: an error-severity faithfulness finding that remains holds the translation and raises a flag review request.

Every stage's result is stored (ModelAttachment role `localize_stage` on the source version), so a run that fails continues from its finished
stages; the same run key started again calls no model and saves nothing. A failure fails the run with its reason; no other model is tried.

The three model calls are made in the procedure's tool by one client (`localize/models.py`), because the judge is a Python callable for Humanus;
their usage is reported to the runner (`model_usage`), so the run's cost counts them.

## Publishing a translation

A translation is published by a person, through the ordinary publish path, unless the site turned on [translating on publish](#translating-on-publish) or the
operator runs `--publish-clean`: both publish only what a run saved cleanly. A localization is a Story lineage of its
own, so the commands are the English Story's, with the version id of the translation:

```sh
papyrus stories versions --story story-waymo--es-419        # the last column is the version id (story-waymo--es-419-vN); publish the newest
papyrus ops content publish --id VERSION_ID [--verify]      # the console's Publish button does the same
papyrus ops content unpublish --id VERSION_ID
```

Where the translation differs from an English Story, in one place each (`src/papyrus_content/localization_publish.py`, called by `publish_item`):

| Rule | What it does |
| --- | --- |
| **The checklist is the provenance** | The English checklist (research, draft, the four review lenses, the cover, the rating) describes how a person or an agent writes a Story; a translation has none of those steps, so `publish_item` does not build or read one for it and writes no sub-task Items. What applies to a translation (translated, checked against the English, copy edited) is proven by the records of the run that saved the version. Nobody ticks it by hand. |
| **A held translation is cleared by a person** | A run holds a translation when an error-severity faithfulness finding remains or its cost reached its ceiling. The version records `metadata.localization.outcome: held` and the run raises a flag review request (`localize-<first 24 characters of the run key>`). Publishing that version is refused (`translation-held`, naming the request) until a person answers it `approve` or `acknowledge` (`papyrus reviews answer --id ID --decision approve`). An open, rejected or missing request keeps it back. A new version of the translation is judged by its own run. A held translation never touches the English Story: its checklist, page and publication are unaffected. |
| **Only while the original is published** | Publishing is refused (`original-unpublished`) unless the original's published row exists. The site serves a translation by the same rule (`PublishedContentSource` leaves out a translation whose original is not published): taking the original down takes the translation's pages, listings and sitemap entry off the site without touching its record, and publishing the original again brings them back. |
| **No rating of its own** | One star rating serves every language of a Story (plan decision 10), and the original passed the site's `publishRequiresRating` gate when it was published. The run does not copy the rating, nothing asks for one, and a machine never creates one. |
| **The site's approval gate is the site's** | A site that requires a person's approval to publish (`publish-gate`) requires it for a translation like any other Story. |

Scheduled publishing and the publish step of `papyrus stories next` read the same `publish_item`: a scheduled translation that is held, or whose original
has been taken down by the time it fires, fails with the same message and shows as overdue.

### What a reader and an agent see

The page of a translation says, in the page's language and apart from the Story's text, that an AI translated it, with a link to the original:

> Traducido por IA del [original en inglés]

- The words are two interface strings of the language, `translation.label` (with `{original}` where the link goes) and `translation.original`
  ([interface strings](multilingual-serving.md#interface-strings)); a public language without them is refused. The label is the page's data, computed from
  the language group (the page is in a language other than the primary's and the group's primary page is served), never text in the Story's body, so a
  correction to the Story cannot remove it and the Markdown the translator sees never contains it.
- Agents read the same facts: the JSON-LD has `inLanguage` and `translationOfWork` (`{@type, url, inLanguage}` of the original), and the Markdown twin
  says `Language: es-419 · Translation: machine · Translated from: <original URL>`. The head has `hreflang` for each published language and `x-default`
  (the original), as for every page of a group.
- Every page of the group lists the others, so publishing or unpublishing a translation (or the original) renders the other languages of the group again,
  in the same projection (`docs/multilingual-serving.md`).
- A new Story announcement is not made for a translation: the new-story alert (`item-published`), the `story.published` notification and the weekly roundup
  leave translations out, because the English Story announced the Story. The `translation.published` notification (admin class, for correctors) is not
  built (below).

### The first live Spanish article, step by step

1. The English Story is published (its own checklist and rating, as always).
2. `papyrus --auth iam stories localize --story LINEAGE --language es-419` (it waits for the run and prints the run's cost and outcome).
3. A saved translation: look at it in the console (the review link of the version), then `papyrus ops content publish --id VERSION_ID`. A held one: read the
   reason on its review request, correct or accept it, answer the request, then publish.
4. `papyrus stories set-slug` first if the drafted address is not the one to keep; it is fixed once published.

## Not yet

- The `translation.published` notification to correctors (admin class) and the correction flow, which records "reviewed by a person" and would change the
  page's label to "translated by AI and reviewed by a person" (PPY-ef71cd, PPY-c0aebc). Until then every translated page says it was translated by AI.
- JSON-LD `translator`: no decision yet on whom to name for a machine translation.
- Quotations marked as translated, with the original wording one tap away (PPY-c0aebc).
- Translating a Story again in the languages already published when only its text changed a little: every new text is a new request (a run translates only the changed blocks).
- Listing keys with the language (`typeStatus`, `sectionStatus`, `headStageKey`), so the console, the reader app and the board show one language at a time
  (PPY-f33254). Until then a published translation appears in those lists beside its original.
- A person's corrections as new versions that are published at once (the correction view); a held translation is cleared or rejected, not edited, today.
- Evaluation harness (PPY-d130d5). Nobody in-house can verify Chinese quality; every measure here is a proxy.
