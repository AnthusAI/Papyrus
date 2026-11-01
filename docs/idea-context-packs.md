# Ideas from context packs: themes, links, concepts and two dates

Design of the context-pack idea pipeline (epic PPY-2e9064). Paths are relative to the repository root. The decisions in the last section are settled (Ryan, 2026-11-01) and the text below follows them.

---

## 1. Current state and why yesterday filed nothing

### 1.1 The monitor-stories task today

* Entry: `src/papyrus_content/monitoring_stories.py` (`run_publication`), called by the router task `{"task": "monitor-stories"}` at 07:30 UTC (docs/monitoring-cloud.md L774-800). It calls `ideas/monitor_stories.draft_monitor_stories` with `limit=None` and the real constraints `time`, `cost` (`MAXIMUM_COST_USD = 0.50`) and `file_error`.
* Candidate funnel, `src/papyrus_content/ideas/monitor_stories.py::collect_monitored_items` (L185-260) and `draft_monitor_stories` (L540-570). A Reference is a candidate only when **all** hold:
1. `curationStatus == accepted` (`DEFAULT_STATUSES = ["accepted"]`, `collect_references` in `ideas/digest.py`);
2. `discoveredByMonitorId` is set and `sourceUri` is present (else `notMonitored`);
3. its lineage is not already the target of an idea (`entity:reference:<lineage>` target, `drafted_lineage_ids`) and no Item is `based_on` it (`has_based_on_story`);
4. the relevance Cyclotron's current `relevance_decision_is` verdict is not the negative label (`judgedNotRelevant`);
5. not promoted (`monitor_promotion.promoted_reference_ids`), not an excluded host, not the same address as a drafted Reference (`sameSource`).
* One Reference → one model call → one idea. The prompt (`SYSTEM_PROMPT`, L75-90) is about a single item; the citation check (`check_story`) allows one handle `I1`.
* Filing: `ideas/items.py::file_idea_item` saves an Item at stage `idea` with front matter `generated` (origin, runId, monitorId, targets, evidence, check) and links each cited Reference `uses_evidence`/`based_on` through `story_reporting.link_reference_to_story`. The gate is `ideas/gate.py::HumanusGate` (rules lane always; judgment lane with the TypeSafe key from SSM). One soft `ReviewRequest` per run (`ideas/review.py`).

### 1.2 Why candidates were 0 on all seven sites

From the funnel and the 10-28 session notes: on 10-29 Anth.us drafted 29 of 40 attempted and "other sites 0 candidates (nothing accepted and monitored)". Since then:

* **Anth.us exhausted its backlog.** With `limit=None` the run drafts every candidate; what was not drafted on 10-29 was drafted on 10-30. Every accepted monitored Reference now has a `based_on` Item, so step 3 removes all of them.
* **New monitored arrivals are `pending`, not `accepted`.** The web monitors deliver `pending` References; `auto_accept.py` accepts only when the learned Wilson lower bound reaches the target precision 0.9, and Anth.us sits at 78.5 % ("accepted 0 so far"). Step 1 removes them (`notAccepted`).
* **The References people and imports added are not "monitored".** Hand-added, email-submitted, CLI-imported and catalogue References have no `discoveredByMonitorId` (`monitoring_intake.py` L66 is the only writer; `knowledge_snapshot/monitor_records.py` L127). Step 2 removes them (`notMonitored`), however many were accepted, commented on or voted on.
* The task has no notion of a theme: nothing reads Messages, accepts, concepts or edges. Hundreds of curation signals per site are invisible to it.

So the result is not a bug in a filter; the design (one undrafted accepted monitored Reference → one story) has nothing left to say once a site is caught up. Also worth noting as fixed numbers the owner's rule forbids: `STORY_DAYS = 90` in `ideas/context.py`, `dedupe.DEFAULT_THRESHOLD = 0.5`, `MINIMUM_FRESHNESS_EXAMPLES = 10`.

### 1.3 What already exists that the design builds on

| Need | Exists | Where |
|---|---|---|
| Ontology with typed edges | `SemanticRelationType` seeds, 44 types, with `allowedSubjectKinds/ObjectKinds`, `isSymmetric`, and (unused so far) `contextPackTags` | `corpora/papyrus-semantic-relation-types.yml`, `src/papyrus_content/relation_types.py`, `amplify/data/resource.ts` L1929-2006 |
| Reference→Reference edge types | `cites` (reference→reference, evidence), `related_to` (symmetric, generic), `supports`, `contradicts`, `derived_from` | same seed file L149-233 (second half) |
| Reference→concept edge type | `mentions` (reference/item/message → semanticNode) | seed file; written by ontology enrichment and the knowledge snapshot |
| Edge record with score/provenance fields | `SemanticRelation`: `relationState`, `score`, `confidence`, `classifierId`, `modelVersion`, `reviewRecommended`, `metadata` JSON, state keys `reference#<lineage>#<state>` | `resource.ts` L1957-2006; `semantic_state_key(kind, lineage, state)` in `src/papyrus_knowledge_query/services.py` L819 |
| Concepts wiki | `/newsroom/concepts`; each page is a `SemanticNode` (`nodeKind` e.g. `concept`, `maker`, `model_family`, `task`); link scheme `concept:` | `lib/wiki.ts`, `docs/knowledge-base.md` L7-9, `knowledge_snapshot/keys.py::entity_key` (`concept--voice-cloning`) |
| Hashtags | **None.** No code mentions hashtags. `Tag`/`ItemTag` are content tags on Items, not concepts | `resource.ts` L2063-2098 |
| Vector search | One S3 Vectors index per site backend, 1536-d `text-embedding-3-small`; vector kinds `reference_summary`, `reference_passage`, `note_source`, `note_passage`, `ontology_concept_profile`, `ontology_relation_explanation`; filterable metadata `corpusId`, `vectorKind`, `kind`, `curationStatus`, `referenceId/LineageId`; only **accepted** References with an `extracted_text` attachment are indexed; sync is a CLI (`knowledge-vector-index --action sync`), not scheduled | `amplify/site-backend.ts` L82-83, L673-735; `src/papyrus_knowledge_query/vector_index.py`; `services.py::S3VectorsProvider` L315-435; `docs/internal-knowledge-research.md` |
| Scan statistic | `scan_window`: windows 1,2,4,8… weeks against the entity's own baseline and the corpus's volume, binomial tail, Bonferroni-corrected; `exceeds_report` for "materially more than last reported" | `src/papyrus_content/knowledge_snapshot/trends.py` L198-290; used by `ideas/trends.py` |
| Learned-not-fixed thresholds | `auto_accept.py` (Wilson bound and latency quantile per publication); `learn_freshness` (tau from the editors' own decision ages) | `src/papyrus_content/auto_accept.py` docstring; `ideas/monitor_stories.py` L268-290 |
| Messages | `Message` + `MessageThread` with `primaryAnchorKind/LineageId/Key`, indexes `listMessageThreadsByAnchorAndUpdatedAt`, `listMessagesByKindAndCreatedAt`, `listMessagesByThreadAndCreatedAt`; Reference threads anchor `primaryAnchorKind == "reference"` | `resource.ts` L1801-1895; `components/conversations-network-source.ts` L32; `components/reference-conversation.tsx` |
| Votes and reasons | On the Reference itself: `curationStatus`, `curationStatusUpdatedAt/By`, `curationStatusReason`, `curationReasonCode`, `curationActorKind` (`human` is the only kind that trains); index `listReferencesByCurationStatusKeyAndUpdatedAt` | `src/papyrus_content/reference_vote.py`; `resource.ts` L1680-1690 |
| Published Stories | `Item` type article/story, `status == published`, `publishedAt`; `load_context` already lists them | `ideas/context.py` |
| Two dates | `sourcePublishedAt` (string) and `createdAt` (ingestion) both exist on `Reference`; also `importedAt`, `retrievedAt`, `feedArrivalAt` | `resource.ts` L1675-1682 |
| Board | PPY-9ff95b (automation direction; item 14 "idea pipeline" and 13 "story similarity index"), PPY-c6aced (votes must train the Cyclotron; loop currently open), PPY-5f8046 closed ("editor decisions on generated stories train the idea pipeline"), epic PPY-781d26 "Messages come only from people", PPY-452419 public conversations | `kbs show <id>` |

---

## 2. Data model

No new GraphQL models. Everything below is rows in `SemanticRelation` with existing fields, plus JSON in `Reference.metadata`. Schema changes (a deploy of all seven backends) are avoided in every slice; the one place a deploy is needed is a resolver for editors to write edges (section 6) and router IAM/config (section 7).

### 2.1 Reference ↔ Reference edges

Predicates, all already in the seed and all allowing reference→reference:

| Predicate | Meaning | Symmetric |
|---|---|---|
| `related_to` | "relates to": the general human link, and the only one the UI offers first | yes (one row, canonical order: lower lineage id as subject; readers query both state-key indexes) |
| `cites` | bibliographic citation (written today by `reference_citation_resolution.py` for papers) | no |
| `supports` / `contradicts` | evidence stance; later slice, offered only when a person asks for a stance | no |

Row shape (one function, `reference_links.link_references(client, a, b, predicate, provenance)`, modelled on `story_reporting.link_reference_to_story` L310-380):

* `id = f"reference-link-{predicate}-{hash_short(a_lineage, b_lineage)}"` so a second write updates, never duplicates.
* `relationState`: `current` (human-confirmed, or derived by a deterministic rule such as citation resolution), `suggested` (machine proposal awaiting a person), `rejected` (a person said no). State keys use the state: `reference#<lineage>#suggested`. Every existing reader queries `…#current`, so suggestions and rejections are invisible to the graph, the knowledge query and the wiki until confirmed. No new field; `semantic_state_key(kind, lineage, state)` already takes the state.
* `score`: cosine similarity when suggested by vectors; `confidence`: the calibrated P(accept) once a calibration exists (2.4 / 3.3), else null.
* `classifierId`: `vector:text-embedding-3-small` for a suggestion, `rule:citation-resolution`, or null for a human link. `modelVersion`: the embedding model or rule version.
* `metadata` JSON: `{"kind": "reference.link", "provenance": "human" | "suggested" | "derived", "suggestedBy": <classifierId or null>, "addedBy": <sub or "auto:vector">, "addedAt", "decidedBy", "decidedAt", "decision": "accepted" | "rejected" | null, "reasonCode", "note"}`. Who/what created it and who decided are both kept, so a confirmed suggestion is distinguishable from a hand-made link (the first trains calibration, the second does not need to).

### 2.2 Reference → concept edges

A concept is a `SemanticNode` (status `accepted`). Its hashtag is the name part of its `nodeKey`: `concept--voice-cloning` → `#voice-cloning`; `maker--anthropic` → `#anthropic`. `knowledge_snapshot/keys.py::entity_key` is the one place the key is built, so the hashtag is `nodeKey.split("--", 1)[1]` and needs no new field. Collisions across kinds (`task--translation` vs `concept--translation`) are shown as `#translation (task)`.

Edge: the existing `related_to` predicate, reference → semanticNode (Ryan's decision 1: tagging a Reference with a concept means it relates to that concept; `mentions` stays for text the enrichment found), with the same `relationState`/`metadata` convention as 2.1 (`"kind": "reference.concept"`). Reasons to reuse rather than add `about_concept`: a human-confirmed concept link needs no new predicate and the seed already allows it; consumers of concept statistics that count only `mentions` are extended to count confirmed `related_to` links from References; the provenance in `metadata` still separates human links from extracted mentions where it matters (training).

### 2.3 Two dates on every Reference

Both fields exist; the work is populating and using them consistently.

| Field | Meaning | Written today | Gaps |
|---|---|---|---|
| `createdAt` (ingestion) | when the Reference row was created on the site | every writer | none; `feedArrivalAt` mirrors it for the feed |
| `sourcePublishedAt` (publication) | the source's own publication date, ISO string, day precision allowed | web monitors (`monitoring_web.py` L126, L162 → `monitoring.py` L285 and `monitoring_queue.py` L131); PDF resolution in `reference_url_text.py` L2998-3030 and L3374-3377, which also stores a `publicationDateResolution` object in `Reference.metadata` | HN monitor, email submissions, hand-added links and catalogue imports leave it null unless the PDF path runs; HTML pages are not resolved (`article:published_time`, JSON-LD `datePublished`, `<time datetime>`) |

Design:

* **Populate on ingestion** by extending the existing publication-date resolution to HTML (`web_structured_metadata.py` already parses structured metadata; add the three date sources above) and running it in the curation stage every Reference passes (`reference_curation.curate_reference`). Provenance goes where it already goes: `metadata.publicationDateResolution = {source: "og:article:published_time" | "json-ld" | "pdf" | "monitor" | "citation-year", precision: "day" | "month" | "year", resolvedAt}`. No schema change.
* **Backfill** with the existing `papyrus references curate --corpus-id … --force` path (it is idempotent and leased), as a one-off per site, bounded by the curation budget, not by a count.
* **Unknown publication date stays null.** Never copy `createdAt` into it. Every analysis declares its basis, and a pack states `dateBasis` per item, so the model never writes "published on" from an ingestion date.
* **Which analyses use which date:**
* Ingestion date (`createdAt`): everything that measures the newsroom's own stream: the acceptance burst and hub signals, arrival volume baselines, `learn_freshness` (editors' reaction time), auto-accept latency, de-duplication of runs. Rationale: these ask "what is happening in this site now", which is when the item arrived here.
* Publication date (`sourcePublishedAt`, falling back to ingestion with the fallback flagged): what the model may say about the world ("published 2026-10-28"), the `resurfaced` signal (publication long before ingestion, i.e. an old source getting new attention), the trend reports and wiki timelines of concepts, and the order of References inside a pack.
* Both: shown side by side in the UI and in packs as `published` / `added`.

---

## 3. Suggestion pipeline (vector search makes curation cheap)

### 3.1 What is embedded

Reuse the site index. Two additions to `vector_index.py`:

1. **`concept_card` vectors** for every accepted `SemanticNode`: `displayName`, aliases, kind label, description (`entity_body` in `knowledge_wiki/pages.py` already composes this text). Today only concepts with an AI profile have `ontology_concept_profile` vectors, so most concepts cannot be found by vector search. Metadata: `kind: semanticNode`, `vectorKind: concept_card`, `nodeKey`, `nodeKind`, `lineageId`, `hashtag`.
2. **Index on acceptance, not by hand.** The router's daily pass (where monitor stories already run per publication) runs `index_reference_passages(action="sync")` for References accepted since the last sync, so the index is never a manual step. Needs the router to hold each publication's `vectorIndexArn` and `s3vectors:QueryVectors/GetVectors/PutVectors` on it (section 7; infra change set).

Cost (real constraint): embedding `text-embedding-3-small` is $0.02 per million tokens; a Reference summary vector is ~300 tokens, so indexing 10,000 References is about $0.06. Suggestion queries need **no new embedding**: `GetVectors` with `returnData` on the Reference's own `reference_summary` key gives the vector, then `QueryVectors` (`topK`) with a metadata filter. S3 Vectors query pricing is per request and per TB scanned, negligible at this scale.

### 3.2 Suggesting related References and concepts

Deterministic job `reference_suggestions.suggest_for(reference)` runs (a) when a Reference is accepted (router pass) and (b) on demand from the UI's "Suggest" button:

* Related References: query `vectorKind in {reference_summary}` with `curationStatus = accepted`, exclude the Reference's own lineage and anything already linked (`current` or `rejected`). The neighbours returned are ranked by cosine.
* Concepts: query `vectorKind in {concept_card, ontology_concept_profile}`; exclude concepts already linked.
* **How many to keep, without a threshold:** take the natural gap. Sort the top-K (K = the API's maximum, a real limit) by similarity and cut at the largest drop between consecutive scores among the first half ("knee"); when there is no clear knee, keep those whose similarity is above the site's own median pairwise similarity of confirmed links (learned, 3.3). Until any links exist, keep the knee only.
* Each kept neighbour becomes a `SemanticRelation` row in state `suggested` (2.1/2.2). Re-running is idempotent (same ids). Suggestions older than the Reference's current version are superseded when the row is rewritten.

### 3.3 Accept/Reject on a suggestion becomes a training signal

* **Accept** sets `relationState: current`, `metadata.decision: accepted`, `decidedBy/At`. **Reject** sets `rejected`. Both are updates to the same row, so the decision history is the row itself (append-only auth on the model: `categoryAppendOnlyOperations`, `resource.ts` L2004).
* **Calibration (deterministic, slice 2).** Per site, over suggestions a person decided, the same statistic `auto_accept.py` uses: the smallest similarity `t` at which the Wilson 95 % lower bound of the accept share among suggestions scored ≥ t reaches the site's target precision. Suggestions above `t` are shown first and marked "likely"; below it they are still offered but marked "possible". With too few decisions, no `t` exists and nothing is marked; this is recorded, like `auto_accept` does. This replaces the knee rule in 3.2 once it exists.
* **Cyclotron (slice 4).** A "link fit" binary classifier on the site Cyclotron (pattern: `site_cyclotron.py` derives Section classifiers from configuration; here one classifier `reference-link-fit`), examples = decided suggestions with features the pack builder already computes (similarity, shared concepts, shared host, publication-date gap, both accepted-by-human). Human decisions, only `curationActorKind == human`-equivalent (the `decidedBy` is a person), are the labels: this meets PPY-c6aced's rule that votes train the site's Cyclotron. Decisions (which suggestions to show as likely) move from the Wilson rule to the Cyclotron when a trained version beats the rule on held-out decisions, the same gate PPY-c6aced asks for.
* **Idea feedback** also trains: an idea Item moved forward or spiked (`story_reporting.move_story_stage`) is a label on its pack (`generated.evidence.packId`), feeding a "pack worth an idea" classifier later (section 4.5). PPY-5f8046 already established that editor decisions on generated ideas are training data.

---

## 4. Signals: a closed set of deterministic pack builders

Each signal is a pure function `(graph snapshot, now) → list[Pack]`, ranked within itself by a p-value from the entity's **own** baseline, so packs from different signals are comparable and no signal has a fixed window or cap. Shared statistic: `knowledge_snapshot/trends.scan_window` generalised from weeks to days (parameterise `DAYS_PER_WEEK`→ bucket length; same windows 1, 2, 4, 8, … buckets, same binomial tail against the corpus volume, same Bonferroni correction). The bucket is a day for Messages and accepts (they are daily events) and a week for concepts, the resolution the snapshot already uses.

The "corpus volume" for each signal is that site's own total of the same event kind, so a site where everything grows does not report everything as rising.

| Signal | Entity | Event series (bucketed) | Baseline | Pack contents |
|---|---|---|---|---|
| `conversation` | a Reference or Story with a Message thread (`primaryAnchorKind` reference/item) | Messages per day in its thread (`listMessagesByThreadAndCreatedAt`) | the thread's own earlier days vs all Messages on the site | the anchor, its Messages (author label, date, text), the References the Messages link to, its concepts and current edges |
| `acceptance` | a concept (`SemanticNode`) | human accepts per week of References that `related_to` or `mentions` it (`curationStatusUpdatedAt`, `curationActorKind == human`, ingestion basis) | the concept's own earlier weeks vs all human accepts | the concept, the References accepted in the window (title, both dates, summary), their edges and co-mentioned concepts |
| `hub` | a recently added Reference | its degree: `current` edges to other References (`related_to`, `cites`, `supports`, `contradicts`) plus shared-concept links (two References sharing a confirmed concept count as one weighted edge, weight 1/√(concept frequency)) | the empirical degree distribution of all References on the site: the hub's percentile, converted to a p-value `1 − F(degree)`; no threshold | the hub and its neighbours (both directions), the concepts they share, Messages on any of them |
| `cluster` | a connected component of recently added References in the graph of `current` edges plus mutual-kNN vector neighbours (k = ⌈√n⌉ of the recently indexed set, a derived quantity; mutual so sparse areas do not merge) | members per day by ingestion | the component's own earlier arrivals vs all arrivals; a component with no earlier arrivals is "new" and ranked by size × mean pairwise similarity, flagged so the model says "emerging" and not "rising" | the members, their edges (confirmed and suggested are told apart), shared concepts, Messages |
| `resurfaced` (slice 3) | a Reference | publication-to-ingestion gap and recent attention (Messages, accepts, new edges) | the site's own distribution of gaps: percentile | the Reference, what pointed attention at it (which Message, which link), its concepts |

Rules all signals obey:

* Only `accepted` References are evidence in a pack (the knowledge-base rule, `docs/internal-knowledge-research.md`). A `pending` Reference may appear as "also pending, not evidence" (Ryan's decision 2).
* Ranking across signals: each pack carries `correctedPValue` and `surprise` (z). Packs are interleaved round-robin by signal in order of surprise, so one noisy signal cannot take the whole run. The run stops only for the real constraints the task already has: `out_of_time()`, `maximum_cost_usd`, `file_error`; and a pack is trimmed only to `synthesis.MAXIMUM_INPUT_CHARACTERS` (context size), dropping the lowest-ranked members first.
* **No repeat without new evidence.** A pack's `anchor` (thread id, concept key, hub lineage, component fingerprint) is recorded on the idea it produced (`generated.evidence`). The same anchor is offered again only when `exceeds_report(new_window, reported_window)` says the new activity is materially more than what the last idea reported (the same test the trend path uses) **or** the pack has at least one Reference not in the last pack. A spiked idea's anchor needs both.
* The "a Reference is never drafted twice" rule becomes "an *anchor* is never drafted twice without new evidence". A Reference may legitimately appear in several theme ideas. `based_on` links are still written for every cited Reference (coverage stays visible on the Reference), and single-item monitor stories (today's path) skip a Reference that any idea already cites, as now.

### 4.5 Which packs get a model call

Slice 1: deterministic, by the ranking above until time or cost stops the run. Slice 4: the site Cyclotron's "pack worth an idea" classifier (labels = editors' forward/spike on ideas, features = signal type, surprise, pack size, share of human-confirmed edges, Message count, days since the last idea on the anchor) orders the packs; the LLM still only writes. Until that classifier beats the surprise ordering on held-out decisions, the ordering stays statistical.

---

## 5. Context pack format and the idea agent

### 5.1 Pack (JSON, built by code)

```json
{
"packId": "pack-<sha256(site|signal|anchor|window)>[:12]",
"signal": {"type": "acceptance", "anchor": "concept--voice-cloning", "windowDays": 14, "count": 9, "expected": 2.1,
             "correctedPValue": 0.0007, "surprise": 3.2, "dateBasis": "ingestion"},
"concepts": [{"handle": "C1", "hashtag": "#voice-cloning", "name": "Voice cloning", "kind": "concept", "description": "...", "recentCount": 9, "baselineCount": 11}],
"references": [{"handle": "R1", "title": "...", "url": "...", "published": "2026-10-27", "added": "2026-10-28", "publishedBasis": "og:article:published_time",
                  "summary": "<the 200-token summary Message, else the metadata attachment summary>", "acceptedBy": "human", "acceptedOn": "2026-10-29",
                  "concepts": ["C1"], "status": "accepted"}],
"edges": [{"from": "R1", "to": "R3", "type": "related_to", "provenance": "human"}, {"from": "R2", "to": "R3", "type": "related_to", "provenance": "suggested", "similarity": 0.81}],
"messages": [{"handle": "M1", "about": "R1", "author": "Editor (handle)", "date": "2026-10-30", "text": "..."}],
"recent_published_stories": [{"title": "...", "section": "...", "date": "..."}],
"existing_ideas": [{"title": "...", "state": "idea|spiked"}],
"mission": "...", "policy": "...", "allowed_sections": ["..."]
}
```

Summaries come from what exists: the `reference_summary_200_tokens` Message linked to the Reference (seed type, written by curation) or the metadata attachment summary (`vector_index._reference_summary_payload_for_indexing`). No page fetch per pack; the single-item path keeps its fetch.

`recent_published_stories` replaces `STORY_DAYS = 90` with "stories published since the anchor's baseline began" (the scan's baseline start), so the window is derived, not fixed.

### 5.2 The idea agent (one model call per pack, GPT-6 Luna via `synthesis.openai_transport`)

* **Prompt**: "You are given a theme the newsroom's own activity surfaced (the signal), the References and concepts in it, what editors said about them, and what the publication recently published. Propose between one and three distinct story ideas about the **theme**, not about any single item." Each idea: headline, dek, section, angle paragraph(s), `cites` handles. Rules carried from `monitor_stories.SYSTEM_PROMPT`: one sentence per entry, ISO dates only as given, no arithmetic, no present-tense claims about the publisher, say where sources are from, never "desk".
* **Structured output** (`SCHEMA` extended): `ideas: [ {headline, dek, section, paragraphs, cites_summary} ]` with `trends.SENTENCE_SCHEMA` sentences; up to three ideas. "Several ideas per run" comes from several packs × up to three ideas each; the model may return one when the theme supports only one.
* **Citation check** (`trends.check_sentence`, already multi-handle): every sentence cites R/C/M handles that exist; numbers and dates must appear in the cited handle's fields; an idea must cite **at least two References** (a theme) and may cite a Message only together with a Reference (a Message is a person's opinion, not evidence). An idea that fails is dropped, not the pack.
* **De-duplication**: `dedupe.split_duplicates` against published stories, current ideas, spiked ideas and the other ideas of the run (existing); plus, once vectors are on the router, a vector check of the idea text against `reference_summary` and idea vectors so the fixed `0.5` word-overlap threshold can be replaced by the site's own distribution of idea-to-story similarities (the learned cut: the smallest similarity at which editors spiked ideas as duplicates, Wilson-bounded). Until then `0.5` stays and is flagged.
* **Filing**: `ItemStore.file_story_draft` with `targets = [entity:reference:<lineage> …]` for every cited Reference (so `based_on` links are written), `generated.evidence = {packId, signal, anchor, window, surprise, citedConcepts, citedMessages}`, `generated.origin = "context-pack"`. Concept citations become current `related_to` edges item → semanticNode (`reference_links.link_item_concept`; `related_to` allows subject kind `item`), provenance `derived`, so the idea appears on the concept's wiki page. The idea body ends with a "Evidence" section listing References (title, published/added), concepts (hashtags) and the signal in one sentence ("9 accepted References mention #voice-cloning in 14 days, against 2 expected").
* **Gate**: unchanged (`HumanusGate`), one soft `ReviewRequest` per run; ideas stay in the Idea column.

---

## 6. UI (in words)

All in the Reference detail (`components/needs-me-reference-detail.tsx`, next to `ReferenceConversation`) and the concept page. Lucide icons; buttons and textareas; the one Accept/Reject vocabulary; text labels beside every mark.

**"Related" section on a Reference**

* Header "Related" with a `Link` icon. Two sub-lists.
* **Concepts**: a row of chips, each `Hash` icon + `#voice-cloning` + kind in parentheses when ambiguous. Confirmed chips are plain. A suggested chip carries a `Sparkles` icon and the word "Suggested" plus "close match 0.81" in text, and two buttons `Check` "Accept" and `X` "Reject". Rejecting opens a one-line textarea "Why not? (optional)" and a "Reject" button; nothing else moves.
* **References**: cards with title, host, "published 2026-10-27 · added 2026-10-28" (both dates, always, "published unknown" when null), the edge type in words ("relates to", "cites"). Suggested cards look like suggested chips: `Sparkles` + "Suggested" + the similarity as text + Accept/Reject.
* **Add**: one textarea with the placeholder "Type # for a concept, or paste a link or a title". As the person types `#…`, the list under the textarea shows up to the knee-cut results of a vector + prefix search over `concept_card` vectors, each a full-width button (`Hash` icon, hashtag, name, kind). Typing a URL or words shows matching References the same way (vector search on `reference_summary`, plus exact `sourceUri` match). Pressing a button writes a `current` edge with provenance `human` and clears the textarea. No dropdowns, no autocomplete popovers.
* **"Suggest more"** button (`Sparkles`): runs `suggest_for(reference)` on demand and appends suggestions.
* Everything degrades: with no vector index the section still lists confirmed links and accepts typed hashtags that exactly match a concept key; it says "Suggestions need the knowledge index" in text.

**Concept page** (`/newsroom/concepts/<key>`): a "Linked by editors" list of References (confirmed `related_to` with provenance human) above the extracted mentions, each with both dates, and the same Add textarea to link a Reference from the concept side.

**Idea card** (Stories board, Idea column): unchanged layout; the evidence section lists the signal sentence, hashtags as chips (`Hash`), and References with both dates.

**Writes**: editors cannot write `SemanticRelation` directly from the browser with safe provenance, so a resolver mutation `decideReferenceLink(relationId, decision, reasonCode?, note?)` and `createReferenceLink(subject, object, predicate)` in the pattern of `amplify/data/message-actions.ts` stamps `decidedBy` from the caller's identity. This is a backend change (deploy to all seven sites, one batch bump per `batch-site-bumps`).

---

## 7. Per-site configuration surface

Everything is data already read by the router (`validate_monitor_stories`, `monitoring_stories.py` L35-52, `docs/monitoring-router-config.example.json`). The `monitorStories` entry grows, absent means on:

```
"monitorStories": {
"enabled": true,
"store": "items",
"singleItem": true,
"contextPacks": {"enabled": true, "signals": ["conversation", "acceptance", "hub", "cluster", "resurfaced"]},
"suggestions": {"enabled": true},
"vectorIndexArn": "arn:aws:s3vectors:…:index/…"
}
```

* `signals` lists which of the closed set run; omitting it runs all that have data. There are no numeric knobs: windows, cuts and thresholds are learned or derived as above; the only bounds are the task's time and cost, which already exist (`MAXIMUM_COST_USD`, per-publication time share).
* `vectorIndexArn` is read from the site's `amplify_outputs.json` (`custom.knowledgeQuery.s3VectorIndexArn`) by `seed_router_config.py`, never typed. Without it, packs run without vectors (`conversation`, `acceptance`, `hub` over confirmed edges still work) and suggestions are off with a logged reason.
* Infra: `infra/monitoring/papyrus-monitoring.yaml` gains a managed policy with `s3vectors:GetVectors/QueryVectors/PutVectors` on the seven index ARNs and the GraphQL fields the signals read (`listMessagesByKindAndCreatedAt`, `listMessageThreadsByKindAndUpdatedAt`, `listMessagesByThreadAndCreatedAt`, `listReferencesByCurationStatusKeyAndUpdatedAt`, `listSemanticNodesByCorpusAndNodeKey`, `listSemanticRelationsByObjectState`, `createSemanticRelation`, `updateSemanticRelation`). Router role capacity: 17 of 20 policies used (docs/monitoring-cloud.md L799); fold the new grants into `RouterIdeaPolicy` rather than add a policy.
* The site's own config (`corpora/papyrus-steering.yml`, `relevanceCyclotron`/`siteCyclotron` blocks) gains nothing in slices 1-3; slice 4 adds the `reference-link-fit` and `idea-pack-fit` classifiers as derived members of `siteCyclotron`, the way Section classifiers are derived, not configured.

---

## 8. Phased plan

### Slice 1 — ideas flow again: `conversation` + `acceptance` packs (S/M, Python + router release, one router change set)

* New module `src/papyrus_content/ideas/context_packs.py` (signals, pack builder, `scan_window` over days), `ideas/pack_stories.py` (prompt, schema, multi-handle check, filing), wired into `monitoring_stories.run_publication` after the single-item pass; log line gains `packs`, `ideasFromPacks`, `packsSkippedNoNewEvidence`.
* Reads only what exists: Messages/threads, Reference vote fields, `mentions` edges from enrichment and the snapshot, and `related_to` edges from editors, published Items, existing ideas.
* Gherkin: `features_backend/idea-context-packs.feature` (a thread that lights up yields one pack and up to three ideas each citing two References; a concept whose accepts are not above its own baseline yields no pack; an anchor already drafted yields nothing without new evidence; a site with no Messages still gets acceptance packs; every idea sits in the Idea stage and passed the gate; a pack states the date basis).
* Acceptance checks: dry run on Anth.us shows ≥1 pack where yesterday showed 0 candidates; the run record names each pack's statistic; no idea cites one Reference only.
* Deploy: Papyrus release + router change set (new GraphQL fields in `RouterIdeaPolicy`). No site deploy, no schema migration.

### Slice 2 — links, concepts and suggestions (M, sites + router)

* `reference_links.py` (edge writer, 2.1/2.2), `reference_suggestions.py` (3.2), `concept_card` vectors and acceptance-time sync in `vector_index.py`, router IAM for S3 Vectors, `vectorIndexArn` in router config.
* Resolver `reference-link-actions.ts` + Related section UI (6) + concept page list. Site deploy to all seven in one batch.
* `hub` and `cluster` signals switch on (they need edges and vectors).
* Gherkin: `features_backend/reference-links.feature` (human link is `current` with provenance; a suggestion is `suggested` and invisible to the graph; Accept/Reject flips state and records who; the knee cut with no learned cut; the Wilson cut once decisions exist; no colour-only marks), `features/reference-related-ui.feature` for the console.
* Acceptance checks: on a Reference with an indexed summary, "Suggest more" returns neighbours without an embedding call; a rejected suggestion never returns; the concept report counts a human concept link.

### Slice 3 — two dates everywhere (S)

* HTML publication-date resolution in curation, `publicationDateResolution` provenance, backfill per site via `references curate --force`; both dates in the feed card, detail, packs; `resurfaced` signal.
* Gherkin: `features_backend/reference-dates.feature` (unknown stays null; monitor-supplied date kept; HTML date resolved with its source; the pack states the basis; the trend series uses publication date, the acceptance series ingestion date).

Built (PPY-2e2461): every series declares `dateBasis`. Packs carry it in `signal.dateBasis` (`acceptance` and the newsroom's own stream: `ingestion`; `conversation`: `message`; `resurfaced`: `publication`); snapshot entities (index and entity files, the concept trend series that wiki timelines read) and trend signals carry `dateBasis: "publication"` (items count in the week of their publication date, an undated item is left out and never dated by ingestion). References in a pack are ordered by publication date, falling back to the added date with `orderedBy: "added"` on the row; `published` stays null when unknown. `resurfaced` reads two percentiles from the site's own data: the share of References whose publication-to-ingestion gap is at least this one, and the share of attended References whose latest human attention (accept or Message) is at least as recent; their product times the number of attended candidates is the corrected p-value, reported within `TrendConfig.significance`. New edges are not part of the attention yet because `SignalInputs` does not load edge dates.

### Slice 4 — learning (M, mostly Cyclotron-side configuration)

* `reference-link-fit` and `idea-pack-fit` classifiers derived in `siteCyclotron`; decided suggestions and idea forward/spike as labels; promotion only when a version beats the statistical rule on held-out decisions (PPY-c6aced's gate); vector de-duplication replaces the fixed `0.5`; hashtags typed in Message bodies become message → concept `related_to` edges (human provenance, written by the `linkMessageHashtags` mutation in the category-action Lambda from the stored Message).

## Decisions (settled, Ryan, 2026-11-01)

1. **Concept links use `related_to`.** Tagging a Reference with a concept means the Reference relates to that concept: a `related_to` edge (reference → semanticNode), which the seed already allows. No new predicate. `mentions` stays for text the enrichment found.
2. **Pending References may appear in packs.** Marked "not yet accepted" in the pack; they are context, never cited as evidence.
3. **Single-item ideas keep running, beside the packs.** Their job is finding individual items worth a post, but they must be chosen by data/signals too (Cyclotron score, votes, comments, links, concept activity), not "every accepted undrafted item". Packs and single-item ideas are balanced by the same signal scores, not a fixed split.
4. **Always collect the reason.** Accept/Reject on a suggestion (link, concept, idea) offers the same optional reason textarea as References; those reasons train the site's Cyclotrons. One standard Accept/Reject-with-reason UI component, shared by References, suggestions and ideas.
