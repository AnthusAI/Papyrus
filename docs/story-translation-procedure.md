# The Story translation procedure

`papyrus.story.localize` (PPY-843a7c) translates one published Story into one language per run, checks it against the English, polishes it
until the findings stop shrinking, and saves it as an unpublished version of the Story's localization. Nothing waits for a person and nothing is
published. Plan: [multilingual publishing](plans/multilingual-publishing.md). Design notes: the procedure stages, budgets and evaluation from the
2026-11-13 design (sections 3.1 to 3.9), with Ryan's decisions of that day.

## The record model

- Every Item version has `language` (BCP 47, Humanus spelling: `en`, `es-419`, `zh-Hans`) and `languageGroupId` (the primary Story's lineage).
- A localization is a sibling lineage `{primaryLineageId}--{language}`. Each version names the primary version it came from
  (`sourceLineageId`, `sourceVersionNumber`, `sourceContentHash`) and has `syncState`.
- A translation has no board stage and stays out of the board and the English listings until the listing keys carry the language (plan, deploy 2).
- Its provenance is a ModelAttachment on the version (role `localization_provenance`): source, models, prompt version, Humanus, language pack,
  policy pack and glossary versions, rounds, reverted blocks, findings by category and severity, cost by purpose and the prediction, outcome, the
  alignment (each block's source block, owner, pinned flag and text) and the checklist steps it proves.

## Starting a run: one door

`LocalizationRequest` (id `{languageGroupId}#{language}`) is the desired-state record: the newest published source version to translate.

```sh
papyrus stories localize --story LINEAGE --language zh-Hans --dry-run            # the plan: blocks to translate, glossary terms, predicted cost
papyrus stories localize --story LINEAGE --language zh-Hans --automation SITE.story-localize [--ceiling-usd 1]
papyrus automations runs --id SITE.story-localize
```

The command writes the request and starts the site's automation for the procedure. A run with no request, or for an older source than the request
names, stops before any model call. The run records its outcome on the request (`saved`, `held`, `waiting`, `failed`, `stopped`, `unchanged`).
Next (M2, PPY-251157): the English publish writes the same request and a worker starts the run.

Register the procedure on a site (once):

```sh
papyrus procedures register --file procedures/newsroom/story_localize.tac --key SITE.story-localize --dry-run --json
papyrus procedures register --file procedures/newsroom/story_localize.tac --key SITE.story-localize
```

## Stages

1. **collect**: the published primary version, the previous localization and its alignment, the glossary entries for the language and section
   (`translation_glossary`), the language's copy-edit pack, the language overlays' register notes, earlier runs' spend; the run key.
2. **budget**: the cost predicted from this language's measured runs (`localize/budget.py`: median cost per source character; Tukey's upper
   fence as the outlier band once four runs exist). A caller's ceiling makes the run wait when the prediction is above it.
3. **translate**: only the blocks whose source changed. Link targets, URLs, citations, code and every directive attribute except `alt`, `caption`
   and `title` are replaced by placeholders and put back by the system, so a translator never sets a link target or a credit.
4. **normalize and parity**: emphasis that would not render is fixed by code (the punctuation moves outside the closing marker); the Humanus
   `translation-faithfulness` parity rules run on each block.
5. **bilingual judge**: GPT-6 Luna through Humanus's judge hook, two passes per block, quotes verified by code.
6. **copy edit**: the language's own policies (typography, translationese, AI-writing tells, house words).
7. **refine**: repairs with a certain fix (a `replacement`) are applied by code; error-severity faithfulness findings, and findings of rules
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

## Not yet

- Publishing a localization (URLs, hreflang, the AI-translated label), listing keys with the language, and the `translation.published`
  notification (M4 and M2 of the plan).
- A person's corrections are honoured through the alignment's owner and pinned flag; the correction view that writes them is not built.
- Evaluation harness (PPY-d130d5). Nobody in-house can verify Chinese quality; every measure here is a proxy.
