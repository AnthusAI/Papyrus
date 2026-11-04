# Context packs for newsroom agents

Every agent working in a section works from one pack, built by `src/papyrus_content/newsroom_context_pack.py`. It makes no model call and gives the same result for the same records. Keeping it in one place means a new signal is a change to one layer, and every agent gets it.

```bash
papyrus assignments context-pack --story <lineage> --profile copywriter
papyrus assignments context-pack --section <id> --profile editor
```

The command only reads. It prints what the agent would be given, what each layer held and dropped, and the pack's hash.

## How a pack is defined

- **`LAYERS`** is the table of everything a pack can hold: each layer's heading, whether it is core or a ring, and the function that builds it.
- **`PROFILES`** defines each agent as data: its role text and its layers.
- **Blocks** are the layers agents share: `STORY_BLOCK` (the assignment, the Story, its References, its conversation, its research), `SECTION_BLOCK` (the concepts the section tracks and the References about them, then what the section has published and its top accepted References) and `PUBLICATION_BLOCK` (the same for the other sections).

| Agent | Needs a Story | Layers beyond the blocks |
| --- | --- | --- |
| `reporter` | Yes | None |
| `copywriter` | Yes | The site's editorial policies, and published Stories in full as examples of the voice |
| `editor` | No | The section's Stories in progress |

To add a signal, change the layer or the ranking it belongs to (`reference_rank` for References). To add an agent, add a profile. To add a kind of context, add a row to `LAYERS` and name it in the profiles that need it.

## Concepts a section tracks

An editor lists, for each section, the concepts it should be especially aware of (for example the confinement problem and the containment problem in a security section). The list is the `trackedConcepts` field of the section: `{conceptLineageId, note, addedBy, addedAt}` for each concept. A site whose data API predates the field reads as tracking none.

```bash
papyrus sections concepts --section <section>
papyrus sections concepts add --section <section> --concept "containment problem" --note "why it matters here" [--create] [--dry-run]
papyrus sections concepts remove --section <section> --concept "#containment-problem"
```

A concept is named by its name, an alias, a `#hashtag` or its node key; it must be current and not rejected. An unknown name fails unless `--create`, which makes an `editor_concept` node exactly as typing its hashtag in the console does (`scripts/fixtures/editor-concept-vectors.json` keeps the two writers identical). Writes happen by default; `--dry-run` previews.

Two layers carry them into every agent's pack, first in the section block:

- **`section_concepts`** (core): one card for each tracked concept with its name, aliases, kind, description, the editor's note and its current links to other concepts, grouped by predicate, links an editor accepted first with the note the editor wrote on the link. A tracked concept that no longer resolves or was rejected is a warning, not a card. Empty when the section tracks none.
- **`concept_references`** (a ring): accepted References tagged with (`related_to`) or mentioning (`mentions`) a tracked concept, best first by the Reference ranking, one line each labelled with the concept. The Story's own References are left out. The budget bounds it.

A person's list always outranks the automatic suggestions of concepts.

## How it is filled

The system text is never trimmed: the role, then the publication's mission and policy, then the section's mission, policy, assignment guidance and kill criteria.

The character budget is the only bound, with no fixed counts and no day windows. Core layers are filled first. If they do not fit, the oldest conversation goes first, then the oldest research, then the summaries of References. Rings then share what is left, each taking up to half of what remains. Entries are whole or absent, and each layer reports what it dropped and why.

The editorial policies are the same rules Humanus checks a draft against, so the writer reads them first. A section's policy replaces the publication's policy of the same key.

## Older builders

Two other builders exist. `ideas/context_packs.py` finds signals for the idea writer. `papyrus_build_assignment_agent_context` in `papyrus_newsroom/newsroom.py` still serves `reporter.tac`, `editor.tac` and `copywriter.tac`, and has fixed budgets. It is retired when those procedures move to this pack.
