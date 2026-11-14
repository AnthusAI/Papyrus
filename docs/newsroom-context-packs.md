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
| `copywriter` | Yes | The section's resolved writing guidelines (`writing_guidelines`, first, in full), the site's editorial policies, and published Stories in full as examples of the voice (the guidelines' exemplars first) |
| `editor` | No | The `writing_guidelines` layer (voice, audience and binding rules only), the section's Stories in progress, and the image types the publication has (the `visual_style` layer, types only) |
| `illustrator` | Yes | The `visual_style` layer in full: the publication's image style, its rules that cannot be loosened and its image types; then the assignment, the Story, its place in the procedure, its References and its conversation |

The `audience_lenses` layer is core, so it is never shed. It is generated from `src/papyrus_content/audience_lenses.py` and cut to the agent's role ([four-lens review](four-lens-review.md)).

The `visual_style` layer is core. It reads the publication's visual style profile ([image style profiles](image-style-profiles.md)) and lists each image type in one plain line, grouped by use, with where its pictures may come from and whether it is read as a thumbnail, then tells the agent to choose a type before asking for a picture. A publication with no profile gets an empty layer and the warning that the style of generated images will be undefined and unpredictable. The wording of every line comes from the profile; the code only supplies the headings.

## Guidelines are data, after the role text

A site's guidelines ([guidelines as data](plans/guidelines-as-data.md)) reach an agent as an add-only layer after its fixed role text. The role text lives in `newsroom_context_pack.py`, names no publication, and no document can change it: the system text is the role, then the editorial context, and a guideline can only add to the user text. `images/prompt_lint.py` (`role_text_wording_in`) fails the build when a role text names a site.

- **`writing_guidelines`** (core, never shed) is the writing guidelines resolved for the Story's section: the publication's document with the section's laid over it, by the rules of the guidelines resolver. The copywriter reads all of it; the editor reads the voice, the audience and the binding rules. Its entry records the slug, version and content hash of each layer used and `fieldSources`, which layer every field came from, so a draft can be traced to the exact guidelines it was written under. A site with no writing guidelines gets an empty layer and the warning `writing_guidelines_missing`; nothing is invented.
- **`visual_style`** reads the publication's image style and lays the section's own image guidelines (when it has them) over it; its entry records both layers' versions and hashes.
- **`voice_examples`** starts with the Stories the section's resolved writing guidelines name as exemplars, in their order and with the editors' notes, then the published Stories as before. No Story appears twice.

`papyrus editorial context` (and the assignment action's editorial context) also lists the guidelines as pointer entries: `writing-guidelines` and `visual-style`, at the publication and at the section, each with its lineage, version and sha256, and the command that reads them resolved. The pack does not ask for them (its layers carry the documents in full).

To add a signal, change the layer or the ranking it belongs to (`reference_rank` for References). To add an agent, add a profile. To add a kind of context, add a row to `LAYERS` and name it in the profiles that need it.

## Site rules

A site rule is a small guideline kind that belongs to the publication alone (no section layer) and that Papyrus reads instead of deciding for itself. It is saved like the other guidelines (`papyrus guidelines save --kind NAME`), versioned, stored as a catalog row plus one S3 file, and a site that has saved none gets the neutral default named below. Code: `guidelines/site_rules.py` (`register_rule_kind`, `read_rule`).

- **`byline`** (PPY-804b7b): who a story may be credited to. `mode` is `honest` (the default: attribute agent work to "AI", name a human in `author` only if that person worked on it, never invent an author) or `pen-names` (with `penNames`, a non-empty list the writer picks from, and an optional `note`). It reaches the copywriter as the core `byline` layer, which says whether it is the default or the site's own version.

- **`figure-rules`** (PPY-cbc0f3): the whole text of the site's figure rules, in one field, `bodyMarkus`. It replaces the packaged general rules (`data/figures/rules.md`) for that site and is never merged with them; `papyrus figures rules` prints the site's text when it has saved one, the packaged text otherwise (and says which). A site that must keep a rule of its own, for example that no generated image shows a real person, writes it here or as a binding constraint of its image profile; image prompts are built from the image profile only.

- **`procedure`** (PPY-8fe7e6): the site's own Story procedure, see [story procedure](story-procedure.md#a-sites-own-procedure). It is not a context-pack layer; the process layer and `papyrus stories next` read it.

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
- **`concept_references`** (a ring): accepted References tagged with (`tagged_with`, or the older `related_to`) or mentioning (`mentions`) a core concept, best first by the Reference ranking, one line each labelled with the concept. The Story's own References are left out. The budget bounds it.

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
