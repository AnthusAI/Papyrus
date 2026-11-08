# Image style profiles

A publication says how its pictures should look once, in one place that editors can read and change: its **visual style profile**. The profile is data in the publication's own backend, a third kind of doctrine next to the mission and the policy. Nothing about a publication's style is written in code. The build step that made this is PPY-6e05fd; the design is `project/wiki/image-toolchain.md` (sections 5 and 6). How the image operations work in general is in [images](images.md).

## Where it lives

- A private `Item` of type `doctrine`, slug `editorial-doctrine-visual-style`, one lineage, a new version for every edit. The structured profile is `metadata.visualStyle`, the review setting is `metadata.imageReview` and the prose guidance is `bodyMarkus`.
- Reading and saving are the operations `image_profile_get`, `image_profile_resolve`, `image_profile_diff`, `image_profile_save` and `image_profile_history` (`papyrus images profile ...`). The **document** you read and save is the profile with `imageReview` and `bodyMarkus` beside it.
- A save lays your document over the current one: objects merge key by key, lists and values replace, `null` removes a key. A save that changes nothing makes no version. The first save passes `none` as the version it expects. `papyrus images profile diff --file F` shows what a save would change, with any change to a binding constraint listed separately, and saves nothing.
- Every edit records who, when and why, and the older versions stay, so a picture can always be traced to the exact style it was made with. A publication without a profile still works: every answer carries the warning `profile_missing`, and a prompt is only the skeleton and the brief.
- `NewsroomSection.visualGuidance` (prose) is the section's own layer. A section can also carry `visualStyle` (see below): one optional JSON field on `NewsroomSection`, available once the site's data API has been deployed with it.

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

**Section and Story overrides.** A section's override is `NewsroomSection.visualStyle` (plus `visualGuidance` prose); a Story's is `Item.metadata.imageStyle` (plus `notes`). Each may set `guidance`, `avoid`, `palette`, `sizes`, `display`, `safeZones`, `sources` and `treatment`, for all types or for one under `imageTypes.<key>`.

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

## What is not built yet

Example pictures (`image_profile_example_add` and `_remove`) and the Administration screens are the next build step. The command line still runs the profile operations itself on the signed-in lane (it does not call the door yet), and on that lane a section's `visualStyle` is not read, so the two can differ for a section that has one until the command line goes through the door.
