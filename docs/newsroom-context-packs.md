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
- **Blocks** are the layers agents share: `STORY_BLOCK` (the assignment, the Story, where it is in the procedure, how it will be reviewed for four audiences, its References, its conversation, its research), `SECTION_BLOCK` (the section's core concepts and the References about them, then what the section has published and its top accepted References) and `PUBLICATION_BLOCK` (the same for the other sections).

| Agent | Needs a Story | Layers beyond the blocks |
| --- | --- | --- |
| `reporter` | Yes | None |
| `copywriter` | Yes | The site's editorial policies, and published Stories in full as examples of the voice |
| `editor` | No | The section's Stories in progress |

The `audience_lenses` layer is core, so it is never shed. It is generated from `src/papyrus_content/audience_lenses.py` and cut to the agent's role ([four-lens review](four-lens-review.md)).

To add a signal, change the layer or the ranking it belongs to (`reference_rank` for References). To add an agent, add a profile. To add a kind of context, add a row to `LAYERS` and name it in the profiles that need it.

## Core concepts of a section

An editor lists, for each section, the concepts it should be especially aware of (for example the confinement problem and the containment problem in a security section). The list is the `coreConcepts` field of the section: `{conceptLineageId, note, addedBy, addedAt}` for each concept. A site whose data API predates the field reads as having none.

```bash
papyrus sections concepts --section <section>
papyrus sections concepts add --section <section> --concept "containment problem" --note "why it matters here" [--create] [--dry-run]
papyrus sections concepts remove --section <section> --concept "#containment-problem"
```

A concept is named by its name, an alias, a `#hashtag` or its node key; it must be current and not rejected. An unknown name fails unless `--create`, which makes an `editor_concept` node as typing its hashtag in the console does (`scripts/fixtures/editor-concept-vectors.json` keeps the two writers identical), through the site's `createEditorConcept` route, so it works on a signed-in session with no AWS login. The name keeps the capitals typed (`"Information flow control"`, `"Non-interference"`); a `#hashtag` or a bare lower-case slug reads with spaces, and `--display-name "Non-interference"` gives other words with the same letters. Writes happen by default; `--dry-run` previews, and `--help` sends nothing.

A link between two concepts, with the words that say how they relate, is `papyrus knowledge entities link --key <concept> --to <concept> --note "..."` (see [cli-login.md](cli-login.md#managing-concepts-from-the-signed-in-cli)). The card above lists it on both concepts with the editor's words.

Two layers carry them into every agent's pack, first in the section block:

- **`section_concepts`** (core): one card for each core concept with its name, aliases, kind, description, why the section cares (the editor's note) and its current links to other concepts, grouped by predicate, links an editor accepted first with the note the editor wrote on the link. A core concept that no longer resolves or was rejected is a warning, not a card. Empty when the section has none. When the core layers are over budget, the machine-suggested links on the cards go first and are recorded as dropped; the links an editor accepted stay whole.
- **`concept_references`** (a ring): accepted References tagged with (`related_to`) or mentioning (`mentions`) a core concept, best first by the Reference ranking, one line each labelled with the concept. The Story's own References are left out. The budget bounds it.

A person's list always outranks the automatic suggestions of concepts.

## How it is filled

The system text is never trimmed: the role, then the publication's mission and policy, then the section's mission, policy, assignment guidance and kill criteria.

The character budget is the only bound, with no fixed counts and no day windows. Core layers are filled first. If they do not fit, the oldest conversation goes first, then the oldest research, then the summaries of References. Rings then share what is left, each taking up to half of what remains. Entries are whole or absent, and each layer reports what it dropped and why.

The editorial policies are the same rules Humanus checks a draft against, so the writer reads them first. A section's policy replaces the publication's policy of the same key.

## The note on a Reference

A Reference keeps one free-text note, `curationStatusReason`, and it holds two different things, so a pack labels it by what it is (`reason_line` in `newsroom_context_pack.py`):

- *How it was found.* A research run files a Reference pending, and its discovery note ("Found by perplexity (undecidability proof): ...") is copied into `curationStatusReason` and into `metadata.ingestion_rationale`. A note equal to that rationale, or any note on a pending Reference nobody has voted on, is "How it was found". It is not an editorial reason and does not raise the Reference in `reference_rank`.
- *The note of a decision*, labelled by the status the decision left: "Accepted because", "Rejected because", "Archived because". A Reference that was voted on and is pending again was reopened: "Note from the last decision".

Before 2026-11-04 every note printed as "Accepted because", whatever the status. A Cyclotron's reason for rejecting a Reference ("This doesn't seem to relate to AI/ML ...") therefore read as a reason for accepting it. Whatever status such a Reference holds, the label now follows the status. In the one-line form of the outer layers the same notes read "accepted because ...", "rejected because ..." and "how it was found: ...". The idea pipeline reads accept reasons only from a person's vote (`curationActorKind == human`) and is not affected.

## Older builders

Two other builders exist. `ideas/context_packs.py` finds signals for the idea writer. `papyrus_build_assignment_agent_context` in `papyrus_newsroom/newsroom.py` still serves `reporter.tac`, `editor.tac` and `copywriter.tac`, and has fixed budgets. It is retired when those procedures move to this pack.
