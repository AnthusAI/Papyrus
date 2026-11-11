# Image style profiles

A publication says how its pictures should look once, in one place that editors can read and change: its **visual style profile**. The profile is data in the publication's own backend, a third kind of doctrine next to the mission and the policy. Nothing about a publication's style is written in code. The build step that made this is PPY-6e05fd; the design is `project/wiki/image-toolchain.md` (sections 5 and 6). How the image operations work in general is in [images](images.md).

## Where it lives

- A private `Item` of type `doctrine`, slug `editorial-doctrine-visual-style`, one lineage, a new version for every edit. It is the `image` kind of guideline document (see the guidelines section of the [agent CLI guide](agent-cli-guide.md)): the database row is only a catalog entry (slug, version, who, when, why, content hash) and the document, text included, is one JSON file in S3 attached to that version. The document is the structured profile with `imageReview` and the prose guidance `bodyMarkus` beside it.
- A site that has not saved its profile again still holds the old inline shape (`metadata.visualStyle`, `metadata.imageReview` and `bodyMarkus` on the row). Those versions are read as they are and never rewritten. The next save, even one that changes nothing, writes the new shape as the next version of the same lineage, and the old version stays. A resolve gives the same effective guidance before and after.
- Reading and saving are the operations `image_profile_get`, `image_profile_resolve`, `image_profile_diff`, `image_profile_save`, `image_profile_history`, `image_profile_init` (a draft) and the example pictures below (`papyrus images profile ...`). The **document** you read and save is the profile with `imageReview` and `bodyMarkus` beside it.
- A save lays your document over the current one: objects merge key by key, lists and values replace, `null` removes a key. A save that changes nothing makes no version. The first save passes `none` as the version it expects. `papyrus images profile diff --file F` shows what a save would change, with any change to a binding constraint listed separately, and saves nothing.
- Every edit records who, when and why, and the older versions stay, so a picture can always be traced to the exact style it was made with. A publication without a profile still works: every answer carries the warning `profile_missing`, and a prompt is only the skeleton and the brief.
- A section's own layer is its **image document**: the same kind at section scope, slug `desk-doctrine-<sectionKey>-visual-style`, stored the same way (catalog row plus one S3 file). It holds the override fields below, plus `bodyMarkus` for the section's prose. Read and save it with `papyrus guidelines ... --kind image --section KEY`. A section without an image document keeps using `NewsroomSection.visualGuidance` (prose) and `NewsroomSection.visualStyle` (one optional JSON field, available once the site's data API has been deployed with it). The document, when there is one, replaces both. The section layer costs one indexed read for the section's versions and, when it has a current one, one attachment query and one download; nothing is read per Reference or Story.

## What a profile holds (schemaVersion 2)

| Part | What it is |
| --- | --- |
| `identity` | A summary, a master prompt, a palette (name, hex, optional token and role), a palette limit, a few mood words and brand-wide examples. |
| `techniques`, `subjects` | Techniques preferred and avoided; how people are shown; what is never shown. The avoided and never items are forbidden everywhere. |
| `treatments`, `uses` | Shared bases that image types build on: a family such as diagram or photograph, and a place such as cover, inline or social card. |
| `imageTypes` | The publication's own kinds of picture, keyed. A type has a label, a one-sentence description, a treatment and a use, `display` (where it appears, the smallest width it is shown at, whether it is a thumbnail), `guidance`, things to `avoid`, `sizes`, `safeZones`, `sources` best first, `examples`, and optionally `figureSystem`, `extends` and `removeFromParent`. |
| `typePreference` | Per use, which types to try first. A use set to `null` (usually inline) has no default: the caller must name a type. |
| `constraints` | Binding rules. Only the publication defines them. |
| `locked` | Fields (`sizes`, `sources`, `palette`, `display`) that image types and sections may not change once a use sets them. |
| `imageReview` | `before_publish` (the default) or `after_the_fact`: whether a picture added without a person blocks publishing. |

A type key, once saved, is permanent. A type is retired with `retired: true` (no longer offered, still resolvable for old pictures), never renamed or removed. A type may not carry its own constraints.

## Sources and the figure system

A type's `sources` are `figure-system`, `stock` and `generated`, best first. A figure-system type points at the publication's figure tools; the image service never draws a diagram. Asking such a type to generate or search is refused with `source_not_allowed`, which names the allowed source and where its rules live.

## How a request resolves

`image_profile_resolve` walks the layers from broadest to narrowest: publication identity, the treatment, the use, the image type (its parents first), the section, the Story. It returns the effective guidance and, for every field, the layer it came from (`fieldSources`), so a reviewer can see which layer contributed each word.

| Kind of field | Rule |
| --- | --- |
| Prose (master prompt, guidance) | Kept in order, each from its own layer. Narrower text is added, never replaces. |
| Lists to avoid | Union. Nothing narrower removes an item, except a type's own `removeFromParent` for an item a parent type added; that is recorded in `fieldSources.removed`. |
| Choices (`sizes`, `sources`, `palette`, `display`, `safeZones`) | The narrowest layer wins, unless the publication locks the field (then the broadest wins). A section or Story may narrow a type's `sources` or `palette` but never add one: an addition is ignored and a warning says so. |
| `constraints` | Always all of them. A section or Story that tries to clear or change them, or to change `removeFromParent` or `never`, is ignored with a warning. A choice a constraint forbids (a photograph treatment where generation is the source) is `constraint_conflict`. |

**Choosing the type.** Name it with `imageType`. For a cover or social card you may leave it out: the first type in `typePreference` for that use whose sources allow what the operation does is used, and the answer says so (`imageTypeChosenBy: default-for-use` and an `image_type_defaulted` warning). Inline, or a use with no default, gives `image_type_required` with the choices and their descriptions. An unknown or retired type is `image_type_unknown` with the choices.

**Section and Story overrides.** A section's override is its image document (or, until it has one, `NewsroomSection.visualStyle` plus `visualGuidance` prose); a Story's is `Item.metadata.imageStyle` (plus `notes`). Each may set `guidance`, `avoid`, `palette`, `sizes`, `display`, `safeZones`, `sources` and `treatment`, for all types or for one under `imageTypes.<key>`.

## Who may change what

- Editors and admins may save a style document.
- Adding, changing or removing a binding constraint needs an admin who is a person. An agent gets `human_required` and nothing is saved; a person who is not an admin gets `not_authorized`. An added or changed constraint is stamped with its next version and who adopted it, when and why.
- Rules cannot be loosened from below: no type, section, Story or request can weaken a constraint or something the publication never wants.

## The prompt skeleton

The only prompt code is `src/papyrus_content/images/prompt_skeleton.py`: the order of the slots (style, treatment, image type, constraints, subject, composition, colours, section, story, avoid) and the joining words. Every segment of the plan names the layer that produced it. With no profile the plan is `Subject: <brief>` and nothing else. A test (`prompt_lint.py`) fails the build if that file holds any wording beyond the skeleton.

## What agents read

- `papyrus editorial context` includes a `visual-style` entry (publication scope, with its version and hash) when the publication has a profile.
- The `illustrator` context pack has a `visual_style` layer: the summary, what is never shown, the rules that cannot be loosened, and the image types, one plain line each grouped by use, followed by the instruction to choose a type before asking for a picture. The editor pack lists the types only. The reporter and copywriter packs do not have the layer. See [context packs](newsroom-context-packs.md).

## The door: the image-service function

The newsroom and MCP reach the image operations through two GraphQL fields on the site's data API, both for editors and admins only:

- `imageRead(op, input, actorKind)` runs an operation that only reads. `imageWrite(op, input, requestId, actorKind)` runs one that writes or spends. The wrong door is refused with `invalid_input`.
- The `image-service` function (Python, `src/papyrus_content/image_service.py`) takes who is asking from the identity AppSync verified (name, and whether the caller is in the `admin` group), never from `input`, and repeats the staff-group check. It runs the same handlers as the command line.
- `requestId` makes a write safe to repeat: the same id from the same person gets the first answer (`repeated: true`) instead of a stale-version refusal.
- `actorKind: "agent"` declares the caller an agent, which can only make the call stricter (an agent cannot change a binding constraint, even with an admin's token). It rests on agents labelling themselves.
- The function reaches the site's own data with its role (the schema grants it query and mutate through `allow.resource`); in this step it reads `Item`, `NewsroomSection` and `KnowledgeCorpus` records and writes new profile versions (`Item`). It holds no secret and calls no provider.
- **Deploying it** needs the site's data API deployed (it adds the function, the two fields and `NewsroomSection.visualStyle`), following the batch rule: one site first, then all. Nothing in the engine deploys by itself.

## Example pictures

An editor shows the style as well as describing it: **good examples** and **avoid-this** pictures, kept for one image type at a time (or `identity` for a few that show the whole brand). The operations are `image_profile_example_add` and `image_profile_example_remove` (`papyrus images profile example add --file cover.png --image-type K --kind exemplar --note "..." --reason "..."`); the build step is PPY-6d878b.

- **Upload.** The existing attachment upload (`createModelAttachmentUpload`, a `PUT` to the signed address, `completeModelAttachmentUpload`) takes two new roles, `visual_example` and `visual_negative`, with PNG, JPEG and WebP (never SVG, because providers take raster images) and a 10 MB cap. Those roles belong to the profile's own item (`item-editorial-doctrine-visual-style`), need the picture's SHA-256, and store the file as `<sha256>.<ext>` under the private `newsroom/payloads/item/...` prefix, so the same picture is one row and one file and nothing is publicly readable. `papyrus images profile example add --file` runs these steps for you, refusing a wrong type or size before it asks the backend for anything.
- **Listing.** The add lists the picture under the image type in a **new profile version** (`attachmentId`, `sha256`, `kind`, `note`, `sendToProvider`, and who added it, as what, and when). Removing it makes another version without it. The file is never copied, moved or deleted, so every older version still lists exactly the pictures it was saved with, and a picture made from it keeps them. A file is deleted only when no version lists it and an admin purges it (not built yet).
- **Types own their examples.** The same file may be listed by two types (one row, two entries). A child type does not inherit its parent's examples, because an example of a thumbnail cover is a poor example of a detailed inline picture. A retired type takes no new examples.
- **Providers.** `sendToProvider` is `false` for every upload until a person turns it on, because the service cannot tell whether a picture shows identifiable people or logos. An agent that asks for it, by an add or by saving a whole document, gets `human_required`. `provider_examples(document, image_type)` (`src/papyrus_content/images/examples.py`) is the one function generation will use: only that type's own good examples a person allowed, never a parent's, never an avoid-this picture.
- **Who.** Editors and admins; agents may add examples (recorded as `agent`).

## Drafting a starting profile

`papyrus images profile init [--file brand.json]` (`image_profile_init`) drafts a starting document: three image types (headline picture, picture in the article, social card) with where each appears, its size and whether it is shown as a thumbnail, plus the brand colours from the file. It holds no style wording; the notes list what an editor still has to write. It saves nothing: the editor corrects the draft and saves it with `image_profile_save`, passing the `expectedCurrentVersionId` the draft gives. When a profile already exists the draft carries a `profile_exists` warning.

## What is not built yet

The Administration screens (Policies > Visual style) are the next piece, and purging an example file nothing lists. The command line still runs the profile operations itself on the signed-in lane (it does not call the door yet). Both lanes lay the same section layer over the profile: the section's image document, else its `visualStyle` and `visualGuidance` fields. When a site's data API cannot yet read the `visualStyle` field, the answer carries the warning `section_style_unreadable` and the document and the prose still apply.

## Generation settings

The `generation` field of the publication's image guidelines says whether the site may generate pictures: `models` (provider, name and optional quality, most preferred first), `spendApproved` (default false), `unreviewedMayPublish`, `perRoundCeilingUsd` and `perDayCeilingUsd`. Only the publication's guidelines hold it; a section's document cannot set it. Only a person may change `spendApproved` or a ceiling; an agent saving such a change gets `human_required`. With nothing configured, or spending not approved, `papyrus images generate` refuses with `generation_not_configured` and calls no provider. `papyrus images capabilities` reads the setting. Prices come from `src/papyrus_content/data/image_model_prices.json`; a picture's cost is worked out from the tokens the provider reports.
