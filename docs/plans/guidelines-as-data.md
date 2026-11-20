# Guidelines as data: writing and image guidelines for each site and section

Status: design, not built. Epic: PPY-2a2a8a (this note is its design). Related: image style profiles (PPY-1f68bf, PPY-6d878b), writing guidelines in Administration (PPY-90e312), publication data import and export (PPY-3fd406), add-only agent instructions (PPY-7a61ca), multi-tenant architecture (PPY-25ffa3, `docs/plans/multi-tenant-architecture.md` in PR #1305).

## What was asked

Ryan, 2026-11-08:

1. A site's writing guidelines and image guidelines are stored as data in its backend.
2. A section can override them, layered on top of the site's defaults.
3. Admins edit them in the newsroom (Administration) and through the `papyrus` command line.
4. Every agent and tool reads them from one shared place: the one section context pack every newsroom agent shares, the backend style profile the image tools use, and the rule that a site adds instructions on top of a fixed base prompt and never replaces it.

Constraints: text lives in S3 and DynamoDB is only the catalog; at most one new index per table per deploy; no AppSync subscriptions; Gherkin specs for every behaviour; ready for `tenantId` later.

## Summary

There will be one kind of record, a **guideline document**. It comes in two kinds, `writing` and `image`, at two scopes, the publication and a section. Each document is a versioned lineage of the private `doctrine` Item that already holds the mission, the policy and the visual style profile. The Item row is only the catalog entry (slug, version, who, when, why, content hash). The document itself is one JSON file in S3, attached to that Item version as a `ModelAttachment`. This needs no new table and no new index.

One resolver lays a section's document over the publication's, field by field, by the rules the image resolver already uses: prose is added, never replaced; lists of things to avoid are joined; a section can replace a choice only where the publication allows it; binding rules belong to the publication alone. Every answer says which layer each field came from, with each layer's version and hash.

Agents, the editorial checks, the command line and the newsroom all reach it through the same operations. Agents get it as a layer of the shared context pack, after their fixed role text, which a site cannot change. Saving writing guidelines also updates the copy-editing checks drawn from them, so the same data instructs the writer and the checker.

## What exists today

Image guidelines are already data. Writing guidelines are spread across data, repository files and code, and some of the data stores text in DynamoDB.

| What | Where it lives now | Read by |
| --- | --- | --- |
| Publication image style (visual style profile, schema 2) | `doctrine` Item, slug `editorial-doctrine-visual-style`; the structured profile in `metadata.visualStyle` and the prose in `bodyMarkus`, both inline in DynamoDB (`src/papyrus_content/images/profile_store.py`) | `image_profile_*` operations, `visual_style.py` resolver, `visual_style` layer of the context pack, `papyrus editorial context` |
| Section image override | `NewsroomSection.visualStyle` (JSON) and `NewsroomSection.visualGuidance` (prose), inline | `visual_style.py` (door only; the command line lane does not read `visualStyle`) |
| Story image override | `Item.metadata.imageStyle` and `notes` | `visual_style.py` |
| Publication mission and policy | `doctrine` Items `editorial-doctrine-mission` and `-policy`, `bodyMarkus` inline | `amplify/functions/shared/editorial-context.ts`, `src/papyrus_content/editorial_context.py`, `console-chat-responder` (Rust) |
| Section mission, policy, assignment guidance, kill criteria | Required and optional strings on `NewsroomSection`, inline | the same three readers |
| Copy-editing checks (Humanus policies) | `EditorialPolicy` rows, scope `publication` or a desk; a desk policy replaces the publication policy with the same key (`src/papyrus_content/editorial_checks.py`) | editorial-checks function, `editorial_policies` layer of the copywriter pack |
| House voice: audience, tone, sentence style, voice patterns, structure, lexicon, headline order | **Repository files** `publications/anthus/style-profile.yml`, `publications/pilobolus/style-profile.yml` | Nobody at run time. `papyrus editorial import --profile` turns a file into Humanus policies once (`editorial_commands.py`); the voice itself never reaches an agent |
| Voice examples, rewrite skill | **Repository files** `publications/*/reference-samples/*.md`, `publications/pilobolus/editorial-rewrite-skill.yml` | Nobody at run time |
| Fixed base prompts | Code: role text in `newsroom_context_pack.py` (`REPORTER_ROLE`, `COPYWRITER_ROLE`, ...), the writing contract in `.agents/skills/copywriting/SKILL.md`, `.tac` procedures | Agents |
| Image prompt skeleton | Code: `src/papyrus_content/images/prompt_skeleton.py`, held to the skeleton by `prompt_lint.py` | Image operations |

The gaps:

- A site's voice is not data. It sits in a repository, only two sites have it, and agents never read it.
- A section cannot override writing guidelines, apart from replacing a whole Humanus policy by key.
- Guideline text is stored inline in DynamoDB rows (profile prose, section prose, the JSON override), against the rule that DynamoDB is the catalog.
- Three readers in three languages each re-read doctrine their own way.

## Design

### 1. One record: the guideline document

| | Publication | Section |
| --- | --- | --- |
| Writing | slug `editorial-doctrine-writing` | slug `desk-doctrine-<sectionKey>-writing` |
| Image | slug `editorial-doctrine-visual-style` (exists) | slug `desk-doctrine-<sectionKey>-visual-style` |

The section slugs follow `buildCategoryDoctrineDefinition` in `lib/doctrine.ts`. The Story-level image override (`metadata.imageStyle`) stays where it is: it belongs to the Story's own versions.

Each slug is one Item lineage, type `doctrine`, status `private`, a new version for every save. A save that changes nothing makes no version. The first save expects version `none`; later saves name the version they replace, and a stale version is refused (the image profile already works this way).

### 2. Storage: catalog row in DynamoDB, document in S3

- **The Item row** holds only catalog fields: `lineageId`, `versionNumber`, `versionState`, `slug`, `tenantSlug`, `section`, `versionCreatedBy`, `changeReason`, `contentHash`. `bodyMarkus` and `metadata` stay empty.
- **The document** is one JSON file written with the existing payload helpers (`putJsonModelPayload` in `amplify/functions/shared/model-payloads.ts`; `build_json_model_payload_attachment` and `upload_attachment_body` in `src/papyrus_content/model_attachments.py`): `ownerKind: "item"`, `ownerId` the Item version id, `ownerVersionKey` from `semantic_version_key`, role `doctrine_document`, stored at `newsroom/payloads/item/<id>/doctrine_document/guidelines.json`. This is the same pattern Story bodies already use (`item_body`). The file holds the structured fields and the prose (`bodyMarkus`) together, so one read returns the whole document.
- **Example images** stay `ModelAttachment` rows on the profile, as PPY-6d878b builds them.
- **Reads** are by index only: `itemBySlug` (or `itemByTenantSlug`) for the current version, then `listModelAttachmentsByOwnerVersionRoleAndSortKey`, then one S3 get. A resolve for a section is two such reads, plus the Story's own row for images. A function may cache a document by `contentHash` for its lifetime. Nothing lists a whole table, and nothing new is written per Reference or per Story.
- **Indexes**: none added. **Subscriptions**: none.

Old versions stay, so a draft or a picture can always be traced to the exact guidelines it was made with: the context pack records each layer's lineage, version and hash.

### 3. What a writing document holds (schemaVersion 1)

The fields are those of today's `style-profile.yml`, so the two existing files import unchanged and Humanus's `policy_pack_from_style_profile` keeps working on them:

| Field | What it is |
| --- | --- |
| `voice`, `audience` | Name of the voice, who the site writes for |
| `tone`, `sentenceStyle`, `voicePatterns`, `structure` | Lists of plain sentences |
| `lexicon.prefer`, `lexicon.avoid` | Words and phrases |
| `glossary` | Current product and proper names: `{term, use, avoid[]}` |
| `headline` | Order and keys of title and subtitle |
| `exemplars` | Published Stories that show the voice: `{storyLineageId, note}`. This replaces the repository's `reference-samples` files; the `voice_examples` layer reads these first |
| `bodyMarkus` | Free prose guidance in Markus |
| `constraints` | Binding rules. Publication only |
| `locked` | Fields a section may not replace (for example `audience`, `headline`) |

### 4. How a section layers over the site

The same rules for both kinds, taken from the image resolver (`visual_style.py`, documented in `docs/image-style-profiles.md`):

| Kind of field | Rule |
| --- | --- |
| Prose (`bodyMarkus`, `tone`, `sentenceStyle`, `voicePatterns`, `structure`) | Kept in order, publication first. The section adds; it never replaces |
| Lists to avoid (`lexicon.avoid`, `glossary[].avoid`) | Joined. A section cannot remove an item the publication avoids |
| Lists to prefer, `exemplars`, `glossary` | Joined; a section's glossary entry for the same term replaces the publication's, unless `glossary` is locked |
| Choices (`voice`, `audience`, `headline`) | The section wins, unless the publication locks the field |
| `constraints` | Always all of the publication's. A section that sets or clears them is ignored with a warning |

The answer carries `fieldSources` (which layer gave each field) and `layers` (each layer's slug, version and hash). A section with no document resolves to the publication's alone. A site with no writing document resolves to nothing, with the warning `writing_guidelines_missing`; nothing is refused (as with images: warn and continue).

For images, the existing resolver keeps all its rules (types, treatments, uses, locks). Only the section layer changes source: it reads the section's image document, and falls back to `NewsroomSection.visualStyle` and `visualGuidance` until the site is migrated.

### 5. One resolver, one set of operations, one door

- **Python package** `src/papyrus_content/guidelines/`: `document.py` (schema and validation), `store.py` (catalog row plus S3 document), `writing.py` (the writing resolver), `layering.py` (the rule table shared with images where it fits).
- **Operations**, added to the image operation table so the command line, MCP tools and newsroom client are generated from one definition: `guidelines_get`, `guidelines_resolve`, `guidelines_diff`, `guidelines_save`, `guidelines_history`, each taking `kind` (`writing` or `image`) and an optional `section`. For `kind: image` they call the existing `image_profile_*` handlers, which stay as aliases.
- **The door**: two GraphQL fields, `guidelinesRead(op, input, actorKind)` and `guidelinesWrite(op, input, requestId, actorKind)`, served by the existing `image-service` Python function. It already takes the caller from the identity AppSync verified, never from `input`; it gains read and write on the site's payload bucket under `newsroom/payloads/item/` (the path `model_payload_storage_path` builds).
- **Who may do what**: editors and admins read; admins save. Changing a binding constraint needs an admin who is a person: an agent gets `human_required`. These are the image profile's rules, except that saving becomes admin-only (see decision 1).

### 6. Agents read it, after a fixed base prompt

- **Context pack** (`src/papyrus_content/newsroom_context_pack.py`): a new core layer, `writing_guidelines`, built from the resolved writing document for the Story's section. It goes into the `copywriter` profile (in full, before `editorial_policies`) and the `editor` profile (voice, audience and constraints only). The `visual_style` layer resolves the section's image document as well as the publication's. Both layers are core, so they are never shed.
- **Fixed base prompt, site additions**: the role text and the writing contract stay in code and always come first. A site's guidelines are added after them, under their own heading, and cannot replace them. `prompt_lint.py` is extended to `newsroom_context_pack.py` role text: no publication-specific wording may be written there.
- **`papyrus editorial context`** (Python `editorial_context.py` and TypeScript `editorial-context.ts`): new entries `writing-guidelines` and `visual-style`, at publication and section scope, each with its lineage, version and hash, so `assignment-action` and any skill see the same thing.
- **Skills**: `.agents/skills/copywriting/SKILL.md` and `skills/image-work/SKILL.md` say to read the resolved guidelines first; they hold no site wording.
- The Rust `console-chat-responder` reads mission and policy only; giving it guidelines is a follow-up, not part of this epic.

### 7. The writer and the checker read the same data

Saving a writing document also plans the copy-editing checks drawn from it, with Humanus's `policy_pack_from_style_profile` and the existing `plan_policies` / `apply_plan` in `editorial_policy_pack.py`:

- Publication document: policies at `publication` scope. Section document: desk policies for that section, which replace the publication policy with the same key (today's rule).
- Every derived policy carries the source `writing-guidelines:<slug>:v<N>`. Only policies with that source are created, updated or disabled by a save. A policy an admin wrote, a starter pack, or a derived policy an admin edited by hand (its source becomes `custom`) is never touched.
- `guidelines_diff` shows the policy changes beside the document changes before anything is saved.

### 8. Newsroom: Administration > Policies > Writing guidelines

Beside **Visual style** (PPY-6d878b), with the same layout:

- A **Site** tab and one tab per section. A section tab shows the effective guidelines with a text label on each field saying where it came from ("Site", "This section", "Locked by site"), never colour alone.
- Fields as listed in section 3; prose in the Markus editor; exemplars picked from published Stories.
- **History**: every version with who, when and why, and a diff between any two.
- **Checks drawn from these guidelines**: the derived policies, with a link to Editorial checks.
- Saving asks for a reason. Lucide icons; flat backgrounds, no borders; one Accept and Reject vocabulary.
- The section editor's "Visual Guidance" box moves to the section's tab under Visual style.

This fulfils PPY-90e312's "one editorial view" for writing guidelines.

### 9. Command line

```bash
papyrus guidelines show    --kind writing [--section S]            # the stored document
papyrus guidelines resolve --kind writing --section S [--story L]  # effective, with sources
papyrus guidelines diff    --kind writing [--section S] --file F   # saves nothing
papyrus guidelines save    --kind writing [--section S] --file F --reason "..." [--dry-run]
papyrus guidelines history --kind writing [--section S]
```

Mutations write unless `--dry-run`. `--kind image` does the same for image documents; `papyrus images profile ...` keeps working. `papyrus editorial import --profile` is replaced by `papyrus guidelines save --kind writing --file`.

### 10. Moving each site over

Following the batch rule: Pilobolus (pre-production) first, then the other six in one batch.

1. Deploy the door and operations (one data API deploy per site, bundled with the version bump that needs it).
2. Write each publication's writing document: from `style-profile.yml` for Anth.us and Pilobolus, empty elsewhere (warning only). Exemplars are chosen by an editor; the repository samples are not copied in.
3. Save the current visual style profile again: a new version whose document is in S3. Readers accept both shapes until every site has moved.
4. Copy each section's `visualStyle` and `visualGuidance` into a section image document; the old fields are then ignored and later cleared.
5. When all seven sites have moved, delete `publications/*/style-profile.yml`, `reference-samples/` and `editorial-rewrite-skill.yml`, and the inline readers.

### 11. Many sites in one service (later)

`Item` already has `tenantId` and `tenantSlug` with an index, so a tenant's documents are found with `itemByTenantSlug`. `ModelAttachment` gains `tenantId` in the multi-tenant plan's additive stage, and the documents move under `tenants/<tenant>/` with the rest of the attachments. The resolver takes an optional tenant and checks every row against it, as `editorial-context.ts` does today. The multi-tenant plan's new `SiteDocument` tables are for site settings and brand; guidelines are editorial doctrine and stay with the mission and policy (decision 6). The publication export (PPY-3fd406) includes both kinds of guideline document.

### 12. What it costs

A resolve is two to five indexed reads and one or two S3 gets, once per agent run or pack build; saves are rare. No per-Reference or per-Story work is added.

## Phases

Each phase ships with its Gherkin specs and is one Kanbus task under the epic.

| Phase | Task | What | Deploys |
| --- | --- | --- | --- |
| 1 | PPY-0796f2 | Guideline document store and the writing resolver (Python, no door) | Nothing |
| 2 | PPY-8d41d7 | Operations, command line and the door | Data API, one site then all |
| 3 | PPY-c16829 | Image documents in S3 and section image documents | Function update |
| 4 | PPY-de286b | Agents read the resolved guidelines (context pack, editorial context, skills) | CLI and function |
| 5 | PPY-457028 | Saving writing guidelines updates the checks drawn from them | Function |
| 6 | PPY-070545 | Administration > Policies > Writing guidelines | Newsroom |
| 7 | PPY-07bc72 | Move the sites over and delete the repository files | Data writes, then a code removal |

Phases 3 and 5 depend on 2; 4 depends on 1 (it can read through the store before the door exists); 6 depends on 2 and on PPY-6d878b's Visual style screens; 7 depends on 2 to 6.

Out of scope, filed as the follow-up story PPY-6672ad: moving mission, policy and section prose out of DynamoDB into S3 the same way; guidelines in the Rust console chat.

## Decisions for Ryan

1. **Who can change guidelines?** Recommended: admins only, for both writing and image guidelines; editors can read them. (Today editors may also save the image style profile.)
2. **Should saving writing guidelines update the copy-editing checks automatically?** Recommended: yes, but only the checks that came from the guidelines; checks someone wrote or edited by hand are never touched.
3. **Can a section loosen the site's rules?** Recommended: no. A section adds to the site's guidance; it may replace only what the site leaves open (for example the audience), never remove a word the site avoids or a binding rule.
4. **Should the mission, policy and section text also move out of the database into files now?** Recommended: yes, as a follow-up right after this epic, using the same storage, so this epic stays small.
5. **What happens to the guideline files in the repository?** Recommended: delete them once every site has moved. Voice examples become links to the site's own published Stories, chosen by an editor.
6. **Where should guidelines be stored?** Recommended: in the private doctrine records that already hold the mission, policy and image style, with the text in S3. The alternative is the new site-settings tables in the multi-tenant plan, which are meant for branding and layout, not editorial rules.
