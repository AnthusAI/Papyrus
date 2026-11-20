# Lifecycles that run themselves

Each record type has its lifecycle written down once, as a file in `src/papyrus_content/lifecycles/` that agents load (`papyrus_content.lifecycles.load("Reference")`, or `describe` for plain words). The design is [section 6 of the always-on agents architecture](design/always-on-agents-architecture.md); the epic is PPY-462d6e. Story is PPY-959e41, Announcement, Delivery and newsletter issues are PPY-a36492 and the newsletters epic.

A file lists the record's stages in order. For each stage:

| Field | Meaning |
| --- | --- |
| `mover` | The responsibility (a key of the catalog in `responsibilities.py`) that moves the record out of the stage, or `engine` for a move the code makes. Never a person. |
| `person` | `never`; `by_policy` (a person is asked below the rung named in `rung`); or `always` (whatever the rung, with `why`). The way to ask is a review request. |
| `nobodyActs.kind` | `moves_on` (nothing waits), `stays` (the record stays and is counted, `counted: true`), `retries` (one retry at a due time, then `then`: `flags` or `stays`) or `flags` (one flag, and the record waits). |

The loader refuses a file that breaks a rule and names every problem: an unknown mover, a person as a mover, a stage asked by policy with no rung, a record that stays without being counted, a kind that spikes, rejects or removes a record for its age. `features_backend/references/reference-lifecycle.feature` holds the rules; each record's own feature holds its file.

## Reference (PPY-bea2bf)

`reference.yaml`: collected, delivered (pending), captured and summarised, predicted, accepted or rejected, rated, grouped. A pending Reference nobody decides stays pending and is counted. Built: the file, the loader and the rules. Not built here: the retry of a transient capture failure at its due time (capture runs in the monitoring router, whose hold is not lifted by this work), and Today's count of References waiting at a stage (a count needs an index or a stored counter, which is a decision the board records on PPY-bea2bf).

## Idea (PPY-f1c774)

`idea.yaml`: generated, selected, assigned for research, spiked. At propose and below a person selects; at draft and above the selecting agent selects, picky, and takes at most what the site's policy allows. An idea nobody selects stays and is counted; none is spiked for its age; a spiked idea records why. Built: the file. Not built: the selecting agent itself (no task builds it yet; PPY-fb1aef is ideation), and Today's count of unselected ideas (a count is an unbounded read of the idea stage unless something stores it, which the board records on PPY-f1c774).

## Translation (PPY-21b8c5)

`translation.yaml`: wanted, translating, held, ready, published, stale. `papyrus_content/localize/lifecycle_state.py` says which of the six each language of a Story is in, from the request a run keeps (`LocalizationRequest`): `story_states(client, source, languages)` is one point read for each language and returns exactly one state for each. `failed` and `stopped` are wanted again (the dispatcher retries them), `waiting` (a cost ceiling) and `held` are held, `saved` and `unchanged` are ready, and a request that names an older source than the Story has now is stale. A hold raises one flag and blocks only that translation. Block-level staleness and pinned blocks are the translation engine's own (`localize/blocks.py`, `translation-correction.feature`); a translator woken for a source edit is the translation agent (PPY-98f88e), not built here.

## Illustration (PPY-ce0dd2)

`illustration.yaml`: needed, candidates made, chosen, placed. Unattended the agent makes one image; a person who is choosing may be given several; a generated image carries no credit and a third-party image is always credited. The step is closed by the records (`story_illustration.cover_evidence`, never by hand) and now stays open for a stock picture whose image line has no credit, as it already did for a missing or brief-copied alt text. Not built: the illustrating agent that makes the candidate unattended (PPY-77148a) and a figure request from another agent as an Assignment for it.
