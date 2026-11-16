# Names in several languages: concept and section labels

A concept (`SemanticNode`) has one identity and one set of edges, and a section has one record. What changes per language is the thing's name, its other names
and a short description. Each of those is an `EntityLabel` row. One model serves concepts (`entityKind: concept`, `entityId` the node's lineage id) and,
later, sections (`entityKind: section`), because the questions are the same: find a thing by its name in a language, list every name of one thing, list the
labels that need work. A second table would need the same three indexes and the same code.

The full design is in the multilingual knowledge graph recommendation (Ryan approved its defaults on 2026-11-15). This page says what is built.

## The row

| Field | Meaning |
| --- | --- |
| `id` | `{entityKey}#{language}` for the preferred name; `{entityKey}#{language}#alias#{folded text}` (or `#hidden#`) for another |
| `entityKind`, `entityId`, `entityKey` | the thing: `concept`, its lineage id, and `concept#{lineage id}` (the partition of the by-thing index) |
| `language`, `role`, `text` | the site's tag (`en`, `es-419`, `zh-Hans`); `preferred`, `alias` or `hidden` (the hashtag of a node key); the name |
| `nameKey` | `{kind}#{language}#{folded text}`: finds the thing by name with one query. Folding: Unicode compatibility form, case folded, white space collapsed. A shared stack puts the tenant in front |
| `sortKey` | `{language}#{role}#{folded text}` |
| `origin`, `pinned` | `primary` (written from the node's own text), `machine`, `human`, `copied`, `pod`; a pinned label is a person's wording and no machine overwrites it |
| `sourceContentHash`, `syncState`, `workKey` | on the preferred row: the hash of the words a translation was made from, `current`, `stale`, `conflict` or `held`, and, only while it needs work, `{kind}#{language}#{state}` (a sparse index) |
| `description`, `equivalence`, `slug`, `provenanceId` | a short description in this language, the degree of equivalence, the page address, the stored provenance |

Indexes: `entityKey` + `sortKey` (every name of one thing), `nameKey` (who has this name), `workKey` + `updatedAt` (what needs work).

## Who writes the primary rows

One writer: the stream consumer `amplify/functions/entity-label-sync`, on the `SemanticNode` table. Every change of a concept, from the console, a command, the
knowledge run or a merge, brings its `origin: primary` rows to what its text says (`src/papyrus_content/entity_labels/primary.py`), and gives a concept with
no language the site's primary language. It writes only when the name, other names, description, key, language or version state changed, so its own writes
start nothing further. It marks translated labels `stale` (or `conflict`, when pinned) when the words they were made from change.

Concepts that exist before the consumer was deployed are covered by one resumable pass: `papyrus --auth iam knowledge concepts label-backfill --apply` (dry run
by default).

## Finding a concept by name

`stories link-concept`, `references link-concept`, `sections concepts`, `links` and `knowledge concepts related` find a concept with `entity_labels.lookup.find_concepts`:
an exact node key, else the name in the caller's language and then the site's primary language (a name, another name or a hashtag are all label rows), else the
hashtag spelling of the typed words. Each reading is one index query. None of them lists the concept table. When no concept is found the error points at
`papyrus knowledge concepts search`, which finds by meaning and by words (and still reads the catalogue, because a substring search cannot use an exact index).

`papyrus knowledge concepts labels --concept NAME` shows every name of one concept in every language.

## Naming a section or a concept in another language

One procedure (`src/papyrus_content/entity_labels/translate.py`) makes a label for a section or a concept in one language:

1. A glossary entry that covers the whole name decides it (its first approved rendering, or the original when the entry is do-not-translate). The model is told the decided name.
2. One structured call to the house model writes the name, other names and description. It may answer that the language has no settled term (`equivalence: none`, `keepOriginal`).
3. The description is checked against its source with the Humanus translation-faithfulness rules and the bilingual judge. A name that another thing of the same kind already has in the language is a collision.
4. Anything wrong (an error finding, a collision, no equivalent term) holds the label (`syncState: held`, in the work index) and raises a flag review request (subject type `label`). A clean label is `current`.

A pinned label (a person's wording) is never overwritten, and a label made from the current words is not made again.

### Sections

`papyrus --auth iam sections labels --language es-419 --language zh-Hans --descriptions-file web/sections.json` names every enabled section: its title and the description from the site's sections file. The projection reads the current labels of each public language and lays them over that language's interface strings as `section.<id>.label` and `section.<id>.description`, so the kicker, the home groups, the section headings and the navigation show the language's own name. A held, stale or missing label gives no words: the page shows what it showed before (a key the language's strings file has, or the original marked as such), never an unchecked name.

The names live in the site's store, not in `web/strings/<tag>.json`. A string in that file with the same key is overridden by the label, so remove such copies when a label exists.

### When a concept is named

A concept is named in a language only when a page in that language needs the name (`entity_labels/triggers.py`). A concept that already has a label in the language is left alone,
in any state but `stale` (a stale one is made again from the changed words); a held label waits for its review request and is never asked for twice. The first trigger
is a Story in a served language being tagged with the concept (`name_concepts_for_story`); the concept's own page being published and a language being switched on
follow, each asking the same function. A trigger changes no concept and publishes nothing.

### The queue of wanted names

Nothing that tags a Story or publishes a translation names a concept itself: naming costs model calls and needs the operator lane, and an editor's or an agent's tool has neither.
It records the need instead: one `EntityLabel` row per concept and language with `syncState: wanted` (`role: wanted`, `origin: wanted`), found through the work index with one
query per language. Recording is idempotent, and it never touches a name: a concept that has a label in the language, in any state, is not recorded, and the primary language
is never recorded. `papyrus --auth iam knowledge concepts localize --needed [--language TAG ...] [--ceiling-usd N]` names what is wanted with the label procedure (a held
label raises its one review request and is not asked for again), drops a row whose concept has a name by then, and stops at the ceiling. What it did not reach stays wanted,
so the next run goes on from there and a rerun costs nothing.

Three events record a need, both before anything else is written so a failure leaves nothing half done: a translation in a language is published (`publishing.publish_item`: the concepts its original is tagged
with are needed in that language), a Story is tagged with a concept (`concept_tags.tag_with_concepts`: the concept is needed in every language the Story is published in), and a concept's own wiki page is published (its `entityKey` names the concept: it is needed in every language the site serves). A site
that has not named its primary language yet records nothing.
