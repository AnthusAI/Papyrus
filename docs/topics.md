# Topics

What the newsroom's recent References are about, on demand. `papyrus topics model` (and the `topics_model` MCP tool) reads the References of a
window of days, finds their topics with the same engine the weekly knowledge run uses, and marks each topic rising, falling, steady or new
against the window before. It is an interactive tool for editors and editor agents. It publishes nothing and changes no record. Epic PPY-d0f028.

Every topic action is one operation in one table, `src/papyrus_content/topics/operations.py`. The `papyrus topics` commands, the MCP tool schema, the newsroom's TypeScript types,
the `topic-work` skill's reference and this page's reference section are generated from it, so they cannot disagree.

**Adding or changing an operation:** edit the table, then run `python scripts/generate-topic-operations.py`. A test fails when a generated file is out of date.

## How a run works

1. **The window.** Whole days, counted back from `--as-of` (today by default), on each Reference's **source date** (`sourcePublishedAt`), never the date
   it reached the newsroom. Presets are `7d`, `14d` (the default) and `28d`. The previous window is the same number of days ending the day before.
2. **The read.** The References come through the index `listReferencesByCorpusAndSourcePublishedAt` (corpus, then source date): only the window is
   read, a page of 100 at a time, never the table. A Reference with no source date, or one that is not written as an ISO date, is not in the index and is
   not seen. Each returned row is then kept or dropped: only the current version; the vote (default accepted and pending, rejected only with
   `--states`); the section its vote was filed under (`--section`); the monitor that delivered it (`--monitor`). `--max-references` is a safety stop only:
   when it is reached the run says so in `warnings` and in the log. There is no other cap.
3. **The text.** A Reference's title and the summary held on its row (`cardSummary`). The engine sees nothing else.
4. **The model.** Both windows are modeled together in one pass, so a topic means the same thing in both. The smallest topic scales with the number of
   References, the square root, never under 3 (`--min-cluster-size` overrides). The engine is BERTopic through Biblicus with the knowledge run's settings
   (`knowledge_snapshot/topic_config.py`), behind the small interface in `src/papyrus_content/topics/engine.py`; tests use a deterministic fake.
5. **The trend.** Each topic's share of the current window against its share of the previous one, by a two-proportion test at 95 percent: **rising**
   (a larger share), **falling** (a smaller share), **steady** (no clear change), or **new** (nothing in the previous window). The result carries the
   mark (`▲ ▼ = +`) and the word, and a legend, so the trend never depends on colour.
6. **The saved id.** A hash of the question, the engine and the exact Reference versions (`id` and `updatedAt`). Asking the same thing of the same
   References finds the earlier answer (`cached: true`) and models nothing; `--refresh` models again. The full record, member lists included, is kept
   in a folder on the machine that ran the command (`PAPYRUS_TOPICS_DIR`, else `~/.cache/papyrus/topics`).

Small windows run inline, on the machine that asked. The engine is behind a plain interface (documents in, topics out, nothing else), so a later cloud
job can run the same call and store the same record; that job, `topics.show` and `topics.members`, and the public Trending block are follow-ups.

## What it needs deployed

The index is one new global secondary index on `Reference`. It uses attributes the table already has, so no backfill is needed. A site gets it when
its data API is released and deployed; until then the command answers `service_unavailable`. A deploy can add only one index per table, so this one
must not share a release with another Reference index.

<!-- generated:topic-operations -->
<!-- Generated from src/papyrus_content/topics/operations.py. Do not edit by hand; run scripts/generate-topic-operations.py. -->

## Operations

| Operation (MCP tool) | Command | Effect | What it does |
| --- | --- | --- | --- |
| [`topics_model`](#topics-model) | `papyrus topics model` | read | Find the topics in the References of the last 7, 14 or 28 days, by their source date, and say which are rising or falling. |

Effect: `read` changes no record in the backend. Every operation needs an editor or admin of the site; readers get none.

## Results and errors

Every call returns one envelope. Success: `{"ok": true, "op", "publication", "result", "warnings"}`. Failure: `{"ok": false, "op", "error": {"code", "message", "retryable", "details"}}`. The commands print the envelope as JSON and exit 0 on success and 2 on any error. `--input-file PATH` gives the whole input as JSON; flags override it.

Every operation may return `invalid_input`, `not_authorized`, `service_unavailable`, `not_implemented`.

| Code | Meaning | Retry? | Details |
| --- | --- | --- | --- |
| `invalid_input` | The request does not fit the operation's input. | no | path names the field |
| `unknown_operation` | There is no topic operation by that name. | no | operation, or command for the CLI |
| `not_implemented` | This operation is described but not built yet. | no | operation |
| `not_authorized` | You are not an editor or admin of this site. | no |  |
| `not_found` | No such section in this publication. | no | section |
| `engine_failed` | The topic engine could not run, so nothing was modeled and nothing was saved. | yes | message says why, for example that Biblicus is not installed |
| `service_unavailable` | A permission or backend check could not be made. Nothing was changed. | yes |  |

## topics_model

Find the topics in the References of the last 7, 14 or 28 days, by their source date, and say which are rising or falling.

- Command: `papyrus topics model`
- MCP tool: `topics_model`
- Effect: read
- Agent may call: yes
- Note: Reads References through the source-date index (listReferencesByCorpusAndSourcePublishedAt); it never scans the table. A Reference with no source date, or one that is not ISO text, is not seen. The section is the one the Reference's vote was filed under. The engine reads each Reference's title and the summary held on its row. The result is kept on this machine under savedId.

Input:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `window` | string | no | How far back to look, counted from asOf on each Reference's source date. Default 14d. One of: `7d`, `14d`, `28d`. |
| `asOf` | string | no | The last day of the window, YYYY-MM-DD (UTC). Default today. |
| `section` | string | no | Only References filed under this section (its id, slug or name). |
| `monitor` | string | no | Only References this monitor delivered, for example hn. |
| `states` | array | no | Which votes to include. Default pending and accepted; rejected only when asked for. |
| `minClusterSize` | integer | no | The fewest References in a topic. Default scales with the number of References: the square root, never under 3. |
| `compareTo` | string | no | previous (the default): also read the window just before and mark each topic rising, falling, steady or new. none: this window only. One of: `previous`, `none`. |
| `maxReferences` | integer | no | A safety stop. Reading ends at this many References, and the result and the log say so. Never a quiet cap; omit it to read the window. |
| `representatives` | integer | no | How many representative References to show per topic. Default 3. |
| `refresh` | boolean | no | Model again even when the same question was answered before on the same References. |

Result:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `savedId` | string | yes | Keeps this run. The same question on the same References gives the same id. |
| `cached` | boolean | yes | True when an earlier answer was found and nothing was modeled. |
| `engine` | object | no |  |
| `window` | object | yes |  |
| `compareTo` | object/null | no | The previous window, or null when no comparison was asked for. |
| `filters` | object | no |  |
| `referencesInWindow` | integer | yes | References read and modeled in the window. |
| `referencesInPreviousWindow` | integer/null | no |  |
| `minClusterSize` | integer | yes |  |
| `unassigned` | integer | yes | References in the window that fit no topic. |
| `legend` | object/null | no | What each trend mark means. |
| `topics` | array | yes | Biggest first. |

Errors: `not_found`, `engine_failed`.

Example input:

```json
{
  "window": "14d",
  "section": "ai-models"
}
```

Example result:

```json
{
  "savedId": "topics-0f3a9c1d2b7e4a65",
  "cached": false,
  "engine": {
    "name": "biblicus-bertopic",
    "version": "1.15.0"
  },
  "window": {
    "start": "2026-10-26",
    "end": "2026-11-08",
    "days": 14
  },
  "compareTo": {
    "start": "2026-10-12",
    "end": "2026-10-25",
    "days": 14
  },
  "filters": {
    "section": "section-ai-models",
    "monitor": null,
    "states": [
      "accepted",
      "pending"
    ]
  },
  "referencesInWindow": 212,
  "referencesInPreviousWindow": 187,
  "minClusterSize": 14,
  "unassigned": 31,
  "legend": {
    "rising": "\u25b2 rising: a larger share of the window than before",
    "new": "+ new: nothing like it in the previous window"
  },
  "topics": [
    {
      "topicId": "t1",
      "label": "open weights, language model, benchmark",
      "terms": [
        "open weights",
        "language model",
        "benchmark"
      ],
      "count": 38,
      "previousCount": 21,
      "trend": "rising",
      "mark": "\u25b2",
      "references": [
        {
          "id": "reference-1",
          "lineageId": "reference-1",
          "title": "An open weights model tops a benchmark",
          "sourceUri": "https://example.invalid/a",
          "sourcePublishedAt": "2026-11-07T09:00:00Z",
          "state": "accepted"
        }
      ]
    }
  ]
}
```
<!-- /generated:topic-operations -->
