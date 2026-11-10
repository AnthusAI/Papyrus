# Reporting on a story: drafts, references and messages

After copywriting come the illustration and typesetting stages, which have no agent or command of their own: see [story-illustration-typesetting.md](story-illustration-typesetting.md). The whole sequence is in [story-procedure.md](story-procedure.md).

A story is an `Item` lineage (see `content-item-lifecycle.md`). Everything an agent or editor records while reporting
it hangs off the story's **lineage id**. Nothing here needs a new table.

| Record | Where it lives | One per |
| --- | --- | --- |
| Draft version | `Item` row `<lineage>-v<n>`, highest `versionNumber` is the latest | save of a draft |
| Reference link | `SemanticRelation`, predicate `uses_evidence`, story to reference | story and reference |
| Message | `Message` in the story's `MessageThread` (`threadKind` `story_reporting`, anchor `item#<lineage>`) | a person's note, written by the person |
| Agent note | `ModelAttachment` (role `agent_note`) owned by the story's first version record, `ownerLineageId` the lineage | an AI agent's note, never a Message |
| Assignment | `Assignment.itemLineageId` | unit of research, reporting or copywriting work |

## Draft versions

Every time an agent changes the article, it records a **new version**; it does not overwrite the old one.

```bash
papyrus stories save-version --story <lineage> --body-file draft.md \
  [--front-matter-file front-matter.yml] \
  --reason "added the Vercel corroboration" [--author-label "ChatGPT"]
papyrus stories versions --story <lineage>
```

Signed in (`papyrus login`), the version records the person who signed in, taken from the sign-in session, as its author, the same
way `stories link-reference` does. `--author-label` is optional there and is ignored (the command says so on stderr), so a version
never names someone else; the backend does not verify the name, so the CLI does not accept one. A session that names no one stops
the save and points at `papyrus whoami`. With an operator's AWS credentials (`PAPYRUS_GRAPHQL_AUTH=iam`) there is no sign-in, so
`--author-label` is required and is recorded as given.

A new version keeps the previous version's board stage. Add `--stage <stage>` (or `--advance` for the next stage before publication) to save the draft and move the stage in one recorded step.

### Saving a draft with its pictures

A draft that uses pictures can carry them in the same command. Put the picture files in a folder next to the draft and
pass `--images <folder>`:

```bash
papyrus stories save-version --story <lineage> --body-file draft.md --images ./pictures \
  --reason "added the architecture diagram" [--author-label "ChatGPT"] [--dry-run]
```

Every local picture the text uses is uploaded exactly as the newsroom editor's "Insert image" does it: a `MediaAsset`
row on the new version (id `media-<version id>-<first 10 hex of sha256 of the stored path>`, the same id the editor and
the Markus import derive) and an S3 object at `media/assets/<story slug>/<file name>` (the same on a tenant site). The saved text then points at
those stored paths. What counts as a picture:

- an `::image{src="..."}` line, or a Markdown `![...](...)`, whose `src` is a relative path that resolves to a file inside the folder (web addresses, absolute paths, and paths the folder does not hold are left alone; the latter are listed as `image-unresolved`);
- its dark version, if any: a file named like the light one with `.dark` before the extension (`figure.png`, `figure.dark.png`), or the file named by `srcDark="..."`. It is uploaded too and the `::image{}` line gets an explicit `srcDark` with the stored path. `srcDark="none"` keeps pairing off. A Markdown `![]()` has no `srcDark`, so its dark file is uploaded but only an `::image{}` line can show it.
- the card pictures in the front matter (`image`, `cover`, `ogImage`, `thumbnail` and their Night counterparts `imageDark`, `coverDark`, `thumbnailDark`): a file name found in the folder is uploaded and replaced by its stored path, and a stored path whose picture was numbered (`assets/<slug>/chart.png` became `chart-2.png` because the folder now holds a different `chart.png`) is moved to the new path, so the card and the social image name the file that was just uploaded. A web address and a rendition path are left alone. A dry run lists each move as `front-matter`. Spec: `features_backend/story-version-images.feature`.
- on the site, a card, a hero or any `<img>` whose address is a stored picture with renditions shows the rendition the article page shows (`features_backend/card-rendition-images.feature`), so a card never depends on the original file being in the site store; the social image tags keep the picture as written.

Everything is checked before any write: at most 10 MB per file; a PNG, JPEG, GIF, WebP, AVIF or SVG picture; and a dark
version whose width-to-height ratio is within 0.5% of the light one's. A rejection names each bad file and saves
nothing. `--dry-run` prints one line per file (light or dark, source file, media id, stored path, size, and which light
picture a dark one belongs to) and writes nothing, to the backend or to S3. Like any save, each run records another draft
version.

**Re-runs and stable paths.** Running the command again with the same files reuses the same stored paths and S3 objects:
a file whose content is already stored for the story (any of its versions) keeps its exact `srcPath`, and the object is
only re-uploaded when the picture changed (compared by sha256). A name that already holds *different* content is never
overwritten; the new file gets `-2`, `-3`, as the editor numbers it. `MediaAsset` rows are keyed by story **version**
(the table is queried by item id, and the editor and the version carry-forward derive `media-<version id>-<hash of
srcPath>` the same way), so each saved version has its own rows pointing at the same objects; a row id repeats only for
the same version and path.

**Where the files live, and whether that moves.** The key is `media/assets/<slug>/<file>` with the slug the story has when
the file is first stored; a story with no real slug yet has the generated `draft-unsectioned-<hash>` slug and the CLI
uses it exactly as the editor does. The path does not move afterwards: publishing, `stories set-slug` and a section
change never rewrite media keys or the saved body (the body keeps the stored `srcPath`), so pictures keep working, and
their URLs stay the same, after publish. A later slug change only affects pictures added after it.

**One key on every site, tenant or not.** The key is always `media/<srcPath>`, never `media/<tenant>/<srcPath>`. The text, the
`MediaAsset` row and the site's renditions all name a picture by its `srcPath` (`assets/<slug>/<file>`), and the renditions
function makes them from the object's key without `media/`, so the key and the `srcPath` must say the same thing. A tenant
site is told apart by its rows and its own backend and site bucket (see [multi-tenancy.md](multi-tenancy.md#story-pictures-and-the-one-key-rule)).
`renditions.media_key_for_source` is the one function that makes the key; the editor, `save-version --images` and the repair
below use it.

**Publishing needs the renditions.** A publish is refused before anything is written when a picture's renditions are not in
the site store yet; the refusal names the picture and gives the command that asks for them. A picture uploaded a moment ago
may simply not be ready: ask again in a few seconds. Signed in, `papyrus ops content renditions --source assets/<slug>/<file>`
asks for a picture's renditions with no AWS login (`--dry-run` lists what it would ask for): it writes the stored picture over
itself, unchanged, using the editor's own access to the bucket, and the site's image function reacts as it does to an upload.
If there is no object at `media/<srcPath>` the command says so. `--backfill` asks for every image under `media/`.

**Pictures saved on a tenant site before the one-key rule** sit at `media/<tenant>/assets/<slug>/<file>` and can never be
published. Repair them without uploading anything again:

```bash
papyrus stories repair-image-paths --story <lineage>           # prints what it would do; writes nothing
papyrus stories repair-image-paths --story <lineage> --write   # copies inside the bucket, then points the media rows at the new keys
```

It reads every version's `MediaAsset` rows, copies each object whose key is not `media/<srcPath>` to that key inside the
bucket (a server-side copy, the same access `--images` uses), and updates the rows' `storagePath`. The copies make the bucket
announce new objects, so the renditions are made as for an upload. The old objects are left where they are. A source object
that is missing is reported and its rows are left alone; the command exits non-zero. It plans by default and writes only
with `--write` (unlike most mutation commands, which write unless given `--dry-run`).

Both sign-in lanes work, and they reach S3 differently:

| Lane | Rows (`MediaAsset`) | S3 objects |
| --- | --- | --- |
| `PAPYRUS_GRAPHQL_AUTH=iam` | IAM-signed GraphQL | the AWS credentials of the caller (bucket from `--bucket`, `PAPYRUS_MEDIA_BUCKET` or `amplify_outputs.json`) |
| `PAPYRUS_GRAPHQL_AUTH=user` (`papyrus login`) | Cognito user token; the `editor` or `admin` group may write `MediaAsset` | the signed-in ID token is traded for temporary credentials from the site's Cognito identity pool, the way the browser editor uploads; the group's `media/*` write rule applies; the identity pool must trust the app client the CLI signed in on (below) |

A site that moved the CLI onto its Prospectus federation client (`cliOnFederationClient`) has the backend register that
client on the identity pool too, with the same Token role mapping as the web client, so a CLI ID token gets the same
`editor` or `admin` group role as the browser. Until a site runs a backend with that change, the exchange fails with "Token
is not from a supported provider of this identity pool". The user lane needs the identity pool id and the media bucket. Signed in, neither needs a file: the site publishes both in
its public `/.well-known/papyrus-site.json` (`media_bucket`, `identity_pool_id`; both public, the bucket is private and reachable only
through the pool's role), and the CLI uses them for the site it is signed in to. An explicit `--bucket` / `PAPYRUS_MEDIA_BUCKET` and
`--identity-pool-id` / `PAPYRUS_IDENTITY_POOL_ID` win, and so does an `amplify_outputs.json` of the chosen site. A site that has not
been rebuilt on a release that publishes them fails with a message that names the site and says to pass the flag or variable. The `createModelAttachmentUpload` presigned-URL mutation cannot serve this command: it only
issues keys under `newsroom/payloads` and `media/payloads`, never `media/assets`.

**Publishing from the CLI.** `papyrus ops content publish --id <item-id>` writes the published records and then projects the
page. Three things to know:

- **Placeholder slugs are refused.** A story created from the CLI keeps the generated `draft-<section>-<hash>` slug (for
  example `draft-unsectioned-1a2b3c4d5e6f7a8b`) until `papyrus stories set-slug --story <id> --slug <new-slug>` gives it
  one. `content publish` (a `--dry-run` too) stops with that command in the error and writes nothing; there is no override.
  Unpublishing is not blocked. (The newsroom's own Publish button does not check this: the editor only requires a non-empty
  slug, so a story published from the console can still go live at a placeholder address.)
- **The signed-in lane projects through the newsroom.** With `PAPYRUS_GRAPHQL_AUTH=user` there are no AWS credentials to invoke
  the content-actions function, so after writing the records the CLI calls the `publishItem` mutation (`unpublishItem` for
  an unpublish) that the console's Publish button calls. It is idempotent: it finds nothing left to change, projects the
  page, and reports whether the page is live. The IAM lane still invokes the function directly. (That second call does not
  announce the publish to the newsletter; the console's Publish does.)
- **No outputs file is needed to publish.** When no `amplify_outputs.json` of the chosen site says whether it projects pages, the signed-in lane still calls `publishItem`, which does nothing on a site that does not project. A file that names a different backend than the chosen site is ignored.
- **A failed projection is a failed command.** If the page could not be projected, the command exits 1 and says the data is
  published but the page is not, with the exact retry: `papyrus ops content publish --id <item-id>` (repeating it changes
  nothing already written). With `--json` the payload has `"ok": false`, `"dataPublished": true`, `"pagePublished": false`,
  `"retry"` and `"message"`. `--no-trigger` skips projection on purpose and is not a failure. `stories set-slug` on a
  published story projects the same way.

To move a story between board stages without saving a draft:

```bash
papyrus stories move --story <lineage> --stage reporting [--reason "why"] [--author-label "ChatGPT"]
```

**`--stage published` does not publish.** It only moves the card; no page is written and nothing goes live. The command prints a
warning on stderr saying so (in a `--dry-run` too; stdout keeps its tab-separated lines) and naming
`papyrus ops content publish --id <item-id>`, which is what publishes.

The `write` line prints only after the move was saved (a failed move prints no `write` line); `--dry-run` prints its `dry run` line. `stories create`, `stories save-version`, `stories link-reference` and `stories set-slug` follow the same rule.

This is the same `Item.stage` update a card move makes. The stage must be one of the content item stages (`idea`, `assignment`, `reporting`, `copywriting`, `illustration`, `typesetting`, `published`, `held`, `spiked`). The move is recorded on the latest version's `metadata.stageMoves` (who, when, from, to and why), which `stories show` lists and the Reporting trail shows under Stage moves; it posts no Message. The `moveStoryStage` GraphQL mutation (input `{ lineageId, stage, reason }`, editor groups) does the same for browser and agent clients.

The new `Item` row gets `versionNumber` n+1, `previousVersionId`, `versionCreatedBy`, `versionCreatedAt` and
`changeReason`; the previous latest version becomes `superseded`. The editor preview always shows the **latest**
version. Older versions are listed in the story's Reporting trail and open read-only. Publishing still publishes the
latest version. Add `--dry-run` to any command to preview.

"Latest draft" and "published" are different records. The **current** record (`versionState` `current`) is the working
draft: saving a version or publishing one makes that record current and supersedes the rest. The **published** record is
the one the lineage's `PublishedItem.sourceItemId` names. Neither is picked by the highest `versionNumber`, and
publishing never changes any record's `versionNumber` (the publish counter lives on `PublishedItem`). `stories set-slug`
always acts on the published record, and keeps the old address as a redirect.

To repair a lineage whose numbers are muddled (duplicate numbers, several current records), preview and then apply:

```bash
papyrus stories repair-versions --story <lineage> --dry-run   # lists the changes
papyrus stories repair-versions --story <lineage>             # renumbers 1..n by creation order, one current record
```

Content is not changed. The live record stays current if the story is published; otherwise the newest record is.

A human editing in the story editor presses "Save draft" to correct the current draft in place, or "Save as new version"
to keep the previous text.

## References: consulted versus cited

Attach a reference as soon as you read it. One link exists per story and reference. Its `role` says what the reference
became:

* `consulted`: found or reviewed during reporting. It may or may not appear in the article.
* `cited`: it is a citation in the article. Give the Markus citation key so the link and the text agree.
* `based_on`: the story is made from this Reference. Every path that makes a story from a Reference writes it, and a later `consulted` or `cited` link never replaces it ([core rules](reference-curation-pipeline.md#6a-stories-based-on-a-reference-core-rules)).

```bash
papyrus stories link-reference --story <lineage> --reference <reference id> \
  --role consulted --note "primary source, sandbox escape write-up"
papyrus stories link-reference --story <lineage> --reference <reference id> \
  --role cited --citation-key pwn2026
```

Signed in (`papyrus login`), the link records the person who signed in, taken from the sign-in session, as who added it. `--author-label` is optional there and is ignored (the command says so on stderr), so a link never names someone else. The label comes from the CLI session, not from the newsroom (the relation is written directly, not through a mutation that stamps the author the way `postMessage` does), so it identifies the person for the trail rather than proving it against a caller who writes the record by hand. With an operator's AWS credentials (`PAPYRUS_GRAPHQL_AUTH=iam`) there is no sign-in, so `--author-label` is required and is recorded as given. The `write` line prints only after the link was saved.

Running `link-reference` again for the same pair changes its role and keeps who added it and when. A signed-in editor's token may
create a `SemanticRelation` but never update one (the model is append-only for the editor and administrator groups, so category notes,
provenance and reference links cannot be rewritten from a browser or a signed-in CLI). When the site refuses that direct update, the CLI
changes the role through the site's `setStoryReferenceRole` mutation (editor and admin groups, `category-action` Lambda). It refuses any
relation that is not a Story's `uses_evidence` source, writes only the role, the citation key, the note, `updatedBy` (from the sign-in)
and `updatedVia`, and never weakens `based_on`. The IAM lane keeps writing the row directly. A site whose backend predates the mutation
answers with a message that says to use the IAM lane until it is deployed ([spec](../features_backend/story-reference-role.feature)). The Reporting trail
shows each reference with its role, note and the person or agent who attached it, and marks a reference "in the text" when
the latest draft's citations include its citation key.

## Linking stories to each other

A story's "See also" list names other stories an editor or agent says to read too (an article to related articles, a larger story to several posts). The link is one
`SemanticRelation` of type `see_also` between two stories (Items), written by `reference_links.link_items` like every reference edge: one row (the lower
lineage id as subject, a deterministic id from the pair), `relationState` `current`, metadata `kind: item.link`, `provenance` (`human` from the CLI, `derived` from the
agent tools), `addedBy`, `addedAt` and an optional `note`. A link a person rejected is never flipped back by any writer (the command prints `rejected` and a
warning; only a person's decision in the newsroom reinstates it). **This is the only supported way to write one, and the public page reads exactly this relation**: the name lives in one constant
(`STORY_LINK_RELATION` in `src/papyrus_content/story_links.py`) that the writer, `stories show` and the tests all use. `SemanticRelation.predicate` is a
free string in the schema, so the guard is in our writers: no command, tool or argument can choose another relation name (`--relation see_also` is
tolerated, any other value is refused with the allowed value), and `link_stories` refuses to write any other predicate or a record without the seeded
relation type. A story-to-story relation someone writes by hand under another name is never shown as See also; `stories show` lists it as an
`unofficial-relation` line (`stories show --json` as `unofficialRelations`) so it is visible instead of silently ignored.

```bash
papyrus stories link-story --story <lineage-or-slug> --to <lineage-or-slug> [--to <...>] [--note TEXT] [--dry-run] [--json]
```

Both ends must be existing stories (any story type, article or post; not a wiki page or doctrine), a story cannot be linked to itself, and everything
is checked before anything is written. `see_also` is symmetric, so A to B and B to A are the same link: if either direction exists the line says
`exists` and nothing is written, so repeating is safe. Each target prints its title, type and stage; a target that is not published yet gets a warning
(not an error) because the public block shows published stories only. Who added it is taken from the sign-in session exactly as for `link-reference`
(`--author-label` ignored when signed in, required on the IAM lane); the `write` line prints only after the save, and `--dry-run` prints `dry run`.
`papyrus stories show` lists the related stories from either end (`related` lines: lineage id, title, type, stage, note).

Agents use the same code through `papyrus_link_stories(story, see_also_stories[], author_label, note?)` (a Tactus tool in
`papyrus_newsroom/tactus_tools.py`, available to every procedure that loads the `papyrus` toolset) and the MCP-shaped `papyrus_link_stories`
(`story_signals_mcp.py`, `additionalProperties: false`, no relation field). Neither has any field for a relation type. No server registers the MCP-shaped table today.

**Linking a story to a Reference ("read this source too").** The same `see_also` also runs from a story to a Reference: a looser association than citing or consulting
(`uses_evidence` stays the reporting trail and is never shown as a related Reference). It is directional, story to Reference, one `SemanticRelation` written by
`reference_links.link_item_reference_see_also` (metadata `kind: item.reference-link`, deterministic id from the predicate, the story lineage and the Reference lineage,
`relationState` `current`, the same provenance, `addedBy`, `addedAt` and `note`). It is idempotent (an existing edge writes nothing), never flips a rejected edge back,
and refuses a Reference that is not accepted, because only accepted References are shown on the page.

```bash
papyrus stories link-story --story <lineage-or-slug> --reference <reference-id> [--reference <...>] [--to <lineage-or-slug>] [--note TEXT] [--dry-run] [--json]
```

All Reference ids are checked before anything is written; if one does not exist or is not accepted the command stops with a plain message naming it and writes nothing (no
override). Each line prints the Reference's title, host and curation status. `stories show` lists them (`see-also-reference` lines; `--json` as `relatedReferences`). Agents
pass `see_also_references[]` to `papyrus_link_stories` (Tactus and the MCP-shaped table). The site build reads these edges into `page.related_references`
([surfable site](surfable-site.md)). `stories check-links` treats a current edge to an accepted Reference as official and flags a state that is not `current`, a wrong kind, a
Reference that is missing or not accepted, and any other story-to-Reference predicate than `uses_evidence` and `see_also`.

**Deploy.** `see_also` is a new seeded relation type. A site accepts the row without it (`relationTypeId` is a plain id and `predicate` a free string; the seed now also allows a Reference object), but its relation-type table should hold it: on each site run `papyrus relations import-types --config corpora/papyrus-semantic-relation-types.yml` (an idempotent upsert of the seeds; the CLI must be the release that carries the new seed). No schema change, no backfill (no `see_also` row exists yet).

**Removing a link is not a command.** The editor and administrator groups can create a `SemanticRelation` but never update or delete one, so removal
needs a backend change: a `status` (or `relationState: retired`) field written through a new route like `setStoryReferenceRole`
(a mutation on the `category-action` Lambda, editor and admin groups, refusing any relation that is not an `item.link`), a reader that skips
retired links, and an `unlink-story` command that calls it. Today an operator on the IAM lane (`PAPYRUS_GRAPHQL_AUTH=iam`) can delete the row, or an
editor can ask an operator to; there is no editor-side retirement. Spec: `features_backend/story-links.feature`.

## Tagging with concepts

A story or a Reference is tagged with a concept by one edge: `tagged_with` (label "tagged with"), from the story or Reference to a `SemanticNode` whose status is
`accepted`, `relationState` `current`, metadata `kind` `item.concept` (stories) or `reference.concept` (References), `provenance` `human` (a signed-in person) or
`derived` (an agent), `addedBy`, `addedAt` and an optional `note`. The writers are `link_item_concept` and `link_concept` in `reference_links.py`; the row id is
deterministic (it includes the predicate), so a repeat is the same row. `mentions` stays for concepts the enrichment found in text. `related_to` was the tag's name
before 2026-11-09: rows under it still exist (the console, the suggestion pipeline and the idea pack builder still write them), so every reader accepts both
(`CONCEPT_TAG_PREDICATES`; the one place to rename again), and the audit lists the old ones as "legacy: migrate". The migration is not built.

```bash
papyrus stories link-concept --story <lineage-or-slug> --concept <name|#hashtag|nodeKey> [--concept ...] [--note TEXT] [--dry-run] [--json]
papyrus references link-concept --reference <id> --concept <name|#hashtag|nodeKey> [--concept ...] [--note TEXT] [--dry-run] [--json]
```

**The pages update at once, without a purge.** After a real write that created a link, `link-story` and `link-concept` (stories) ask the site to re-render exactly the published stories whose page changed (both ends of a story link; the story of a Reference or concept link; a Reference has no public page) with `papyrus ops content rerender --story LINEAGE --no-invalidate` behind the scenes. Nothing is purged: the HTML lifetime is five minutes, so the link shows within about five minutes. Each story prints `rerender  LINEAGE  no purge  ok`, then `visible on the site within about five minutes; nothing was purged`. A dry run, a repeat that wrote nothing and unpublished stories re-render nothing; `--no-rerender` skips it. At most 20 stories are re-rendered per command; the rest are listed as exact commands. A failed or timed-out re-render is a warning on stderr naming the stories and the manual command (a timeout may still have completed on the server); the link stays and the command succeeds. The server has no batch path, so the stories are re-rendered one after another and one call can take about a minute; a progress line `rerendering LINEAGE (about a minute)...` is printed on stderr before each, and the wait follows `PAPYRUS_GRAPHQL_TIMEOUT_SECONDS` (30 seconds signed in, 120 on the operator lane, when it is unset), so raise it for a command with several targets or pass `--no-rerender` and re-render later. The agent tools `papyrus_link_stories` and `papyrus_link_concepts` do the same and return a `rerendered` list (and `rerenderWarnings` on a failure).

These are rigid on purpose, because an outside agent uses them. No option or field chooses a predicate, a state or a new concept (`--predicate`, `--relation`,
`--state` and `--create` are refused). A concept is never created: it must already be an accepted SemanticNode, found by exact node key, exact hashtag (the part after
`--`) or exact name or alias, ignoring case, never fuzzily. An unknown name is an error listing the closest accepted concepts; a name several kinds share
(`task--translation`, `concept--translation`) is an error listing them, and a node key picks one; a concept that is rejected or suggested is refused. Every concept is
checked before anything is written. A tag that already exists in any accepted form (`tagged_with`, the older `related_to`, or a `mentions`) is reported as `exists` and
nothing is written; a tag a person rejected stays rejected (the line says `rejected`; only the newsroom reinstates it). Each line says whether the concept has a public
wiki page (a published wiki page whose `entityKey` is the concept's slug, the part after `editor_concept--`, or its whole node key) and warns when it has none: the
story page links a concept only once a page exists. Who added it comes from the sign-in as for `link-reference` (`human`); on the IAM lane `--author-label` is required
(`derived`). The agent tool is `papyrus_link_concepts(target_kind, target, concepts[], author_label, note?)` (Tactus, `tactus_tools.py`; `target_kind` is `story` or
`reference`) and the MCP-shaped entry of the same name in `story_signals_mcp.py`. The older `papyrus references link --concept` (editors; it can create a concept and
writes `related_to` through the site's `createReferenceLink`) is not the agent route.

`papyrus stories check-links [--story ...] [--json]` and `papyrus references check-links (--reference ID | --corpus-id ID) [--json]` are read only audits. They list every
story-to-story, story-to-concept and Reference-to-concept relation that is not the official shape: a wrong predicate or kind, a state that is not `current`, a concept that
is missing, not accepted or without a public page, a story target that is not published, a legacy `related_to` tag, and duplicate pairs. `mentions` to an accepted
concept is an accepted shape. Fixing is out of scope. Cost: the stories audit reads the published-story summaries once, then three index reads per story (25 keys to a
request) and one batched concept read; the References audit reads the corpus's accepted References through `referencesByCurationStatusKey` and the same three index reads
per Reference (827 References: about 100 relation requests), with no table scan. Specs: `features_backend/concept-tags.feature`.

## Suggesting related content

Ryan, 2026-11-09: linking a story to related articles, posts and References starts from the story's concepts and is computed from the graph, with no model call, so a
person or model judges a short ranked list. Two hops: first the **related concepts**, then the **carriers** of those concepts.

```bash
papyrus stories suggest-links --story <lineage-or-slug> [--kinds articles,posts,references] [--limit N] [--min-score S] [--include-linked] [--json]
papyrus stories suggest-associations (--story <lineage-or-slug> | --reference <id>) [--kinds articles,posts,references] [--limit N] [--json]
papyrus knowledge concepts related --concept <name|#hashtag|nodeKey> [--limit N] [--json]
papyrus knowledge concepts search "free text" [--limit N] [--json]      # or: --list
```

`suggest-links` is read only. The story's own concepts weigh 1.0 when curated (`tagged_with`, or the older `related_to`) and 0.4 when only an accepted `mentions`. Related
concepts add: a confirmed concept link (`related_to`, `same_as`, `alias_of` between two concepts, with the explanation a person wrote) about 0.5, a concept that appears
together with one of the story's on the newest 60 published stories and accepted References that carry it about 0.3 times a lift-based strength (so hubs do not dominate;
at least 2 shared carriers and lift 1.5). Then every published article, post and accepted Reference that carries any of those concepts is scored: the sum of the concept's
weight times its rarity (`ln((N+1)/(df+1))`), a mention counting 0.6 of a tag, with up to 10% more for recent content. A concept carried by more than 25% of the published
stories counts at a low weight. Left out: the story itself, stories already linked by `see_also` in either direction, References already linked by `uses_evidence` (any role)
or a `see_also` edge from the story, unpublished stories, References that are not accepted, and concepts that are not accepted. Output is grouped **See also**
(articles), **Posts** and **Related findings** (References), top 5 each by default: score, title, type, date or host, the shared concepts by readable name, the path
(`direct` or `via A, then B`), and the exact ready command (`papyrus stories link-story --story <lineage> --to <lineage>` or `--reference <id>`). A story with no accepted
concept says so; tag it first with `link-concept`. The last line is the request count (about 20 to 35 for one story on the live Machines on Machines site; no table is
scanned: indexes and 25-key batched gets only).

`concepts related` lists the concepts near one concept with the reason (`confirmed`, `alias`, `linked`, `cooccurrence`), found with the same exact resolver as
`link-concept` (never created, never fuzzy). `concepts search` finds accepted concepts for free text by meaning: the text is embedded once (`text-embedding-3-small`, the
same provider as `references suggest-links`) and only `concept_card` and `ontology_concept_profile` vectors are queried; popularity never affects the order. A typed
exact (then prefix) concept name or alias comes first, labelled `name match`; the rest are `meaning`. Each result shows the similarity, whether the concept has a public wiki
page (a published `wiki_page` Item whose `entityKey` is the bare slug, the part of the node key after `--`, read from the published-item summaries when the type index is empty;
the same check `stories link-concept` and `check-links` use), how many published stories and accepted References carry it (information only), and duplicate flags in three
tiers: `same name` (equal once case and punctuation are ignored, or the same words in any order), `likely duplicate` (concept cards at least 0.90 alike) and `possible
duplicate`, a suggestion for a person to check (cards at least 0.60 alike and a shared word of 4+ letters; the two "contextual integrity" cards are only 0.66 alike).

**Free-text search needs an embedding key and is not validated against live data.** It embeds the query with `OPENAI_API_KEY`, which must be set and valid in the shell. The
signed-in editor lane has no embedding key (unlike `references search`, which embeds on the server through the `searchReferences` query), so there the command stops with
that explanation instead of a raw HTTP 401. A server-side lane (a new query field next to `searchReferences`) is a follow-up. Name matches, `--list`, `concepts related` and
`suggest-links` need no key. It says plainly when the index has no concept vectors or is missing some accepted concepts, and prints the `knowledge-vector-index --action sync` command that
repairs it. `--list` prints every accepted concept alphabetically. Agent tools (read only, closed argument lists): `papyrus_suggest_links`, `papyrus_related_concepts`,
`papyrus_search_concepts` (Tactus `tactus_tools.py` and `story_signals_mcp.py`). The story checklist has a **Related content** step (`related_content`, not required) that
points here. Code: `src/papyrus_content/link_suggestions.py`, `concept_search.py`; specs: `features_backend/suggest-links.feature`.

**`suggest-associations` (no search phrases to invent).** `suggest-links` needs concepts the story already carries. `papyrus stories suggest-associations --story X` (or
`--reference X`) builds one query from the item itself (title, summary, the first ~300 words of the body) and (1) finds the accepted concepts that text names: the
concept's name, aliases and `#hashtag`, matched as whole words (a short name is never found inside a longer word; a name of three letters or fewer keeps its letter case),
ranked by rarity and position (title over summary over body); no model, no embedding key, so it works in the signed-in editor lane. When the shell has `OPENAI_API_KEY` and a
vector index, the concepts nearest the text by meaning are added, otherwise one `NOTE` line says it matched by name only (a server-side concept query is still the follow-up above).
(2) The top concepts seed the `suggest-links` graph pass (weight 0.4 to 0.8, below a curated tag), so related articles, posts and References are ranked even for an untagged
item. Every concept and candidate prints its exact `link-concept` / `link-story` command; a concept the item already carries is marked `already tagged`. For a Reference the
related stories carry `papyrus stories link-story --story <candidate> --reference <id>`, and its own text comes from the curation card and stored text (title alone if those
cannot be read). Read only: it never writes a relation (it does not use `references suggest-links`). Code: `src/papyrus_content/association_suggestions.py`; specs:
`features_backend/suggest-associations.feature`.

## Notes: people write Messages, agents write agent notes

Messages come only from people. A person's note is a `Message`, and the newsroom, not the caller, says who wrote it. An AI agent never
writes a Message: it saves an **agent note**, kept on the story and shown labelled as AI. Pick the command by who is writing.

**A person's note** (`stories note`). It goes in the story's ordered thread, with author, time and kind, and shows in the story's Reporting
trail (Messages view). Signed in (`papyrus login`), the command posts through the `postMessage` mutation, which stamps the author from the
sign-in. `--author-label` is ignored there (the command says so on stderr), so a note always names the person who signed in.

```bash
papyrus stories note --story <lineage> \
  --summary "Check the second source before we lean on it" \
  --body-file note.md [--kind note|research_packet|reporting_context_packet|draft_note|editor_note] \
  [--reference <reference lineage>] [--version <n>]
```

`--reference` ties the message to a reference you discuss (its lineage id); `--version` ties it to the draft version it is about. The `write`
line prints only after the note was saved. A refusal or any other failure exits non-zero with one line, for example
`The note was not saved: GraphQL request failed: Not Authorized to access postMessage on type Mutation`. A `--dry-run` prints its dry run line and writes nothing.
With an operator's AWS credentials (`PAPYRUS_GRAPHQL_AUTH=iam`) there is no sign-in to name the author, so `--author-label` is required and the
message is written as a system message from an operator (`role` `system`, `authorKind` `operator`), never as a person.

**An AI agent's note** (`stories agent-note`).

```bash
papyrus stories agent-note --story <lineage> --agent "ChatGPT" \
  --summary "Vercel corroborates the host-memory disclosure" --body-file note.md \
  [--reference <reference lineage>] [--version <n>] [--dry-run]
```

The note is one small JSON attachment (`ModelAttachment`, role `agent_note`, media type `application/json`) owned by the story's first
version record (`ownerKind` `item`, `ownerLineageId` the lineage), so every version of the story reads the same notes. The body holds the
agent's name (a label, not an identity), who ran it, when, the summary, the text and the optional reference and version. On the signed-in
lane the command calls the `addStoryAgentNote` mutation (editor and admin groups only, handled by the content-actions function), which records
the signed-in editor's `sub` itself; nothing the caller sends can set it. There is no thread, no Message and no new model. `stories show` lists
each agent note (`agent-note`, time, `AI agent <name>`, summary), and the story's Reporting trail merges them into the Messages list by time,
marked **AI agent** in words and with an icon, never by colour alone.

There is no separate "insight" record: a note about a reference or a story is a person's note or an agent note.

**A limit that rests on instructions.** An agent that works under a person's own login cannot be told apart from that person by `postMessage`,
so an agent that runs `stories note` after `papyrus login` writes a Message under the person's name. Agents are told to use `stories agent-note`
(the reporting skill does). The newsroom enforces the rest: nothing it writes on its own is a Message. The same applies to the generic
`createModelAttachmentUpload` mutation, which editors can also call: it accepts the `agent_note` role, so only `addStoryAgentNote` stamps who ran the agent.

The other writers that still create Messages without a person (research and reporting packets, the console chat, forum posts and web-context turns) are the rest of stage 2 of the rule, epic PPY-59edce.

## Reading it back

```bash
papyrus stories list [--stage STAGE] [--section ID|SLUG|NAME] [--limit N]
papyrus stories show --story <lineage> [--bucket day|week|none]
papyrus stories set-stars --story <lineage> --stars <0-5> [--agent NAME] [--dry-run]
papyrus references show <reference lineage id or record id> [--corpus-key KEY]
papyrus assignments show --assignment <id>
```

`stories list` prints the lineage ids that `stories show --story` takes. The lineage ids of the References that `stories show` lists are accepted by `references show` (so are the `...-v1` record ids that `references list` prints). `assignments show` prints an Assignment's status, type, queue, section, Story and holder, then its events.

`stories list` also takes `--type article|post`, `--stars N` (0 finds unrated Stories), `--min-stars N`, `--max-stars N` (these two match rated Stories only), `--sort updated|stars|rank` and `--bucket day|week|none`. After the six original columns it appends the layout signals by their layout names: `stars` (the effective quality rating, 0 when unrated), `source` (`editor` today, `none` when unrated), `votes`, `bucket` (the rolling window: `week:0` is the last seven days, `week:1` the seven before; `none`; `undated`), `type`, `words` and `published` (the last-published date). `--sort stars` is rated high to low with unrated last; `--sort rank` is what the Articles and Posts page shows first: it calls the projection's own `rank_entries` (newest bucket first, rated Stories first inside a bucket, then newest first) with the site's default bucket. The rating comes from the Item rows the list already reads in one batched request, so a list costs no request per Story and never reads the private rating map. `stories show` prints a `signals` line (type, section, bucket, stars, source, votes, words, published) and, for an editor rating, a `rating` line (ratedBy, ratedAt). `stories set-stars` sets the editor's rating (1 to 5, 0 clears) through the `setItemStars` mutation, so the site re-renders the listings whose order changed; it prints the previous and new rating and writes unless `--dry-run`. The effective rating is read in one place (`effective_rating` in `item_stars.py`); a vote aggregate would plug into `aggregate_rating` there. Ratings are private: none of this output reaches a published row, page, twin or feed. The MCP tools `stories_list`, `stories_show` and `stories_set_stars` (`story_signals_mcp.py`) use the same names (`minStars` for `--min-stars`).

`stories show` prints the latest version, how many versions exist, each stage move, every attached reference with its role, each Message on the Story's threads (`message`, time, `<author> (<kind>)`, summary; oldest first, active ones only) and each agent note (labelled `AI agent <name>`).

`stories create` prints the new version's record id on the `created` line (`created  content-item-...-v1`) and the Story's lineage id on its own labelled line (`lineage  content-item-...`). The lineage id is what every other command takes as `--story`.

## Assigning research and the reporter context pack

An editor can attach a research assignment, with their own direction, to a Story. The assignment works on the Story's lineage, in the Story's section.

```bash
papyrus stories assign-research --story <lineage> --direction "Find the court rulings on model output" \
  [--direction-file direction.md] [--type research.multi] [--title "..."] [--dry-run]
```

The run opens and reads the sources it finds; its packet lists any it could not open ([what a run reads](automated-publication-research-workflow.md#multi-search-research-researchmulti)). The assignment is open, its type defaults to `research.multi`, its title to the Story's title, its `instructions` and `metadata.direction` hold the direction, and its `metadata.contextProfile` is `reporter`. An `AssignmentEvent` records the creation. A Story at the `idea` stage moves to `assignment` through the recorded stage move (`stories show` lists it); a Story at any other stage stays where it is. The command does not fire stage-entry triggers; run `papyrus stories fire-triggers` if the stage should start one. `--dry-run` writes nothing.

### Assigning research in the newsroom

The same assignment can be made on the Story page, at every stage of the Story (components `assign-research-box.tsx`, `assign-research-client.ts`, `lib/assign-research.ts`). The Messages view's Work section starts with an Assign research box: one text area for what the research should find out, and one button. An empty direction is refused in words, before anything is written. Only editors and admins reach the editor, and the backend's own groups decide who may write an `Assignment`.

The browser writes the same stored shape as the command: the `Assignment` row (type `research.multi`, `itemLineageId`, the Story's section when it is one of the site's sections, status `open`, queue `research:<section>:exploratory`), the first `AssignmentEvent`, and two `ModelAttachment`s owned by the Assignment. **The Assignment model has no `metadata`, `brief` or `instructions` column** (PR 1110 was a live bug from writing them as columns). The `metadata` attachment (`role` and `sortKey` `metadata`, JSON) holds `direction` and `contextProfile: reporter`, which the context pack and the research run read through `assignment_metadata`; the `assignment_instructions` attachment holds the direction as text. A Story at the `idea` stage then moves to `assignment` through `moveStoryStage`; if that move fails the assignment stays and the box says so. Specs: `features/newsroom-assign-research.feature` (the box), `features_backend/browser-assign-research.feature` (the pack is built from what the browser wrote; the browser's records are recorded in `features_backend/fixtures/browser-assign-research.json` by `scripts/test-assign-research.ts`, and `UPDATE_FIXTURES=1` rewrites it).

The Work section shows each research assignment with the editor's direction, its state in words and with an icon, when it was made, and the packet once it is finished. A worker runs it: [the research-assignments task](monitoring-cloud.md#research-assignments).

| Stored status | Shown as |
| --- | --- |
| `open` | Waiting for the research worker |
| `claimed` | Running |
| `completed` | Finished, with the packet |
| `failed` | Failed, with the reason from its latest failed event |

The packet is read from the Assignment: the Message on its `produces` relation, and that Message's `metadata` attachment (`research`). Each claim names its sources by the `rank` of a `source_snapshots` entry, and the card links each claim to the pages it cites. The summary, the recommended angle, the disagreements and the open questions follow. A "Could not verify" list (`unverifiedClaims`: `claim`, `sources`, `verdict`, `reasons`) labels each entry in words and with an icon, in four groups: Contradicted by its sources (`contradicted`), Not shown by the sources this run had (`not_shown`, and `rejected` in packets made before the split; it does not mean the claim is false), Needs a check (`needs_check`) and Not checked (`unchecked`), and gives the machine reasons in plain words (`unmatched_terms: Rodney` reads "Not in the cited source: Rodney", `judge_partly_supported` reads "The source only partly supports this"). The fact-check line is made from `factCheck.counts`, for example "12 verified, 8 need a check, 2 contradicted, 6 not shown by the sources; 23 rest on one site". Both are left out when the packet has none. Nothing is added to a message thread: Messages come only from people.

`papyrus assignments context-pack` shows what a reporting agent is given. It only reads.

```bash
papyrus assignments context-pack --story <lineage> [--assignment <id>] [--direction TEXT] [--format text|json] [--max-characters N]
```

The pack (contract `newsroom-context-pack/v1`, module `newsroom_context_pack.py`) is built without a model, the same way every time. Its `system` text is never trimmed: the profile's role text, the publication mission and policy, and the Story's section mission, policy, assignment guidance and kill criteria. A section with no mission or policy is a warning in `warnings`; nothing is invented, and a missing publication policy stops the build. Its `user` text has ten layers, most specific first, and `layers` reports each one's entries (with source ids), characters, `droppedCount` and `droppedReason`:

| Layer | Holds |
| --- | --- |
| `assignment` | The editor's direction, the assignment title and who asked |
| `story` | Title, deck, the current version's text, stage, type and section |
| `story_references` | References linked to the Story (any role), with title, address, summary, published date, accept reason, stars, the note on the link, and the notes editors wrote on how they connect to other References |
| `related_references` | The other end of every `related_to` edge on the Story's References, in both directions, each once, with the full summary, its curation status (accepted or pending), the Story Reference it connects to and the editor's note. An edge a person accepted ranks first, then suggested edges by descending `score`; rejected edges and rejected References never appear. A Reference here is not repeated in the outer layers |
| `story_conversation` | Messages on the Story's `story_reporting` and `story_conversation` threads, oldest first, with author |
| `prior_research` | The research packets earlier assignments on this Story made, newest first: the direction given, summary, claims and open questions |
| `desk_published` | Published Stories in the same section, newest first |
| `desk_references` | Accepted References that belong to the section: curated for it (`curationSectionId`), or used as evidence (`uses_evidence`) by any other Story in the section at any stage, ideas included; best first |
| `publication_published` | Published Stories in other sections, newest first |
| `publication_references` | Accepted References in other sections, best first |

The outer layers are for awareness, so each entry is one line: title, date, address and the first sentence of the summary or deck, with the accept reason and stars when an editor gave them. Full summaries appear only in `story_references`. A Reference whose title is empty or is only its address shows no title line in the top layers, and in a one-line entry it leads with the first sentence of its summary. The outer layers leave out system item types, retired Items, the Story itself and References already in `story_references`. Rejected and pending References never appear. References rank by an editor's vote or stars first (stars, then a written reason), then by newest; an auto-accepted Reference ranks below every one an editor voted on or rated. Reads go through the client, so a tenant's pack holds only that tenant's records.

There is no fixed count and no day window. `max_characters` is the only bound; without `--max-characters` it defaults to 100,000, half of the 200,000 characters the research run allows its model input. The first five layers are filled first. If they alone exceed it, the oldest conversation messages go first, then the oldest research, then the References' summaries, and the layer records what it dropped. The room left is shared outward in halves: `desk_published` may use up to half of it, `desk_references` up to half of what is then left, and so on, with unused room rolling forward. Entries are whole or absent, and published Stories are read newest first only until a layer's share is full. The ranked Reference layers rank on the Reference records and read an entry's summary only when the entry is considered for the budget. The related-References layer reads the edges already stored (`current` and `suggested` states of `related_to`; a rejected edge is in neither state key) and does not use the References search, which is a `searchReferences` query open only to signed-in editor and admin sessions, not to the IAM lane the authoring client uses, and whose meaning lane runs inside that service. The layer takes half of the room left after the first five layers (assignment, Story, its References, conversation and earlier research); the outer layers share the rest.

`contextHash` is a hash of the rendered `system` and `user` text and the layers' provenance, excluding any fetch time; it changes when the policy, the Story or any included record changes. `editorialContextHash` is the hash of the editorial context inside `system`.

`papyrus assignments research-multi <assignment>` uses the pack when the assignment's `contextProfile` is `reporter` and it works on a Story: the pack's `system` text is put before the planning and synthesis prompts, and the pack's `user` text is the brief. The packet records the pack in `multiSearch.contextPack` (the two hashes and the size of each layer, never the text). The packet Message stays a machine record linked to the assignment by `produces`; it is not added to any thread, because Messages come only from people. The Reference records made from the proposed sources are linked to the Story as `consulted` (a Reference the Story already has, in any role, is left as it is). The Story's text is never changed. Other assignments behave as before.

With a pack, the brief starts with the editor's direction, labelled as the editor's, and the planning and synthesis prompts add rules that the direction outranks the Story: the planner gives each thing the direction asks for its own queries in proportion to what it asks, does not re-find what the Story's References and related References already hold, and names a person, place or case only when the brief does; the synthesis answers the direction in its order, with claims or an open question for each thing it asks, a list as one claim per item with its own source, and the Story's existing cases after. Only titles and snippets count as evidence. Runs with no pack keep the plain prompts.

### Taking the sources in

A pack-driven run takes in only the sources a claim or a disagreement position cites (`--cited-only`, the default for a run with a pack and the option `papyrus assignments process-proposals --assignment A [--message M] [--cited-only]` for a packet already written). The citations are read through the packet's `multiSearch.sourceProviders` index-to-URL list; every source stays in the packet. A URL the corpus already holds as a Reference, in any status, is not registered again and its status is not touched; it is linked to the Story as `consulted` like the new ones. New sources are registered `pending`. Without `--cited-only` the intake behaves as before: every proposed source is registered, under an id made from its URL, so a source already registered under that id is rewritten.

The corpus key is `--corpus-key`, else the assignment's `corpusKey`, else the backend's own. A key the steering file (`--config`, optional) lists keeps its configured settings and classifier. Otherwise the key must be the backend's canonical `KnowledgeCorpus`, and its configuration is built from that record with no classifier (the classifier id is an optional field on the records written, which nothing reads, and the router's Reference delivery writes none). A key that is neither fails with `Unknown --corpus-key`. `references create-from-catalog` follows the same rule: a `--corpus-key` the steering file does not list is checked against the backend's canonical corpus (it passes when it names that corpus, and the error names the real one when it does not), and the record id form `knowledge-corpus-<key>` is accepted. The `next` command that `stories assign-research` and `assignments create-research` print is therefore one the catalog and run commands accept. If the intake fails after the packet is written, `research-multi` does not exit with an error: it records a `research.multi.intake_failed` event on the Assignment and returns `intakeError` in its result.

A cited-only run then curates the References it took in: it reads each source with the existing capture stage and writes the Reference's summary with the Assignment's title and the editor's direction, and the titles, decks and sections of the Stories the Reference is linked to, as the reason the newsroom is reading it ([directed summaries](reference-curation-pipeline.md#directed-summaries-why-the-newsroom-is-reading-this-source)). That context is a hint about what to bring forward and where the source does not answer the question; it is never evidence, and the summary still says only what the source says. The summary is shared by every reader of the Reference, so a link made later does not rewrite it (`--force` does). A summary or capture failure is recorded on that Reference's curation card and in the run's `curation.failed`; the run still completes.

## Acting as the signed-in person (the normal path)

Ryan, 2026-11-05: agents just do things on his behalf. An agent working in a signed-in `papyrus login`
session accepts, rejects and rates References and Stories **as that person**: the decision is recorded
as theirs (a human vote the Cyclotron learns from), with no delegation, code or approval step. Only the
editor and admin groups may do it (checked in the schema and again in the handler).

```bash
papyrus references approve --reference <record id> --agent Claude
papyrus references reject --reference <record id> --agent Claude --note "<why, in the person's words>"
papyrus references set-stars --reference <record id> --stars 1-5|clear --agent Claude
```

Each writes unless you pass `--dry-run`. A rejection needs a reason: `--note` or `--reason-code`.
`--agent` is optional. Where the action came from is kept as a plain note, never a gate: the person's
name gets ` via cli (Claude)` (or ` via signed-in` when the site has not named a separate CLI client or the
token's client cannot be read) in `curationStatusUpdatedBy` and `starRatedBy`. Newsroom actions carry no note.

Delegation (below) is optional and not the normal path. It still works for anyone who uses it, and the
commands take it only when you pass `--delegation-file`, `--delegation-token` or `--on-behalf-of`.

## Approving a Reference on a person's behalf

Until a deployment includes the delegation mutations, an agent that runs
`papyrus references review-curation` changes a Reference's admission status, but
the curation is recorded without a human actor kind and never teaches a
classifier. Do not tell a person their approval was recorded as a label unless
the command below printed "on behalf of".

When a person tells you, in a live session, that a Reference is approved or
rejected, the system records it as the person's own label, but only with a
delegation the person granted. You cannot assert it yourself, and your own
judgment never becomes a label this way.

1. The person signs in to the Newsroom and creates a delegation (the
   `createCurationDelegation` mutation): your agent name and how long it lasts
   (eight hours by default, 72 at most). They hand you the token it shows once.
   They can revoke it at any time (`revokeCurationDelegation`).
2. Record their decision. The token can be passed as `--delegation-token` or as
   `PAPYRUS_DELEGATION_TOKEN`:

   ```bash
   papyrus references approve --reference <record id> --on-behalf-of <person's sign-in email> \
     --agent <your name> --instruction "<the person's exact words>" --note "<their reason>"
   papyrus references reject --reference <record id> --on-behalf-of <person's sign-in email> \
     --agent <your name> --instruction "<the person's exact words>" --reason-code out_of_scope --note "<their reason>"
   ```

3. The `recordDelegatedCuration` mutation checks the token (unexpired,
   unrevoked, granted to your agent name, granted by the person you named), then
   records the curation as the person's on the Reference: `curationActorKind: human`, and
   `curationDelegation` holding `relayedBy` (your agent name), `delegationId` and `instruction`, the person's
   words as you quoted them. The token proves the person let you relay decisions,
   not that they made this one, so the quote is what makes each label auditable.

### Getting a delegation without pasting a secret (device authorization)

Prefer this flow: the secret is made on the agent's machine and never passes
through chat or through the server in plaintext.

1. The agent runs:

   ```bash
   papyrus references request-delegation --agent <your name> [--hours 8] --wait
   ```

   It generates `curation-delegation-<uuid>~<random secret>`, writes it to a
   private file (mode 0600, by default under `~/.config/papyrus/delegations/`,
   or `--token-file <path>`), sends only the SHA-256 hash
   (`requestCurationDelegation`), and prints only an approval code such as
   `ABCD-2345` and the file path. The secret is never printed.
2. Tell the person: open the Newsroom, Delegations, approve that code. The
   request is pending for ten minutes, and at most five can be pending at once.
3. The person approves (`approveCurationDelegation`) or denies
   (`denyCurationDelegation`). Approval makes them the grantor and starts the
   requested lifetime (default eight hours, 72 at most). `--wait` polls
   `getCurationDelegationStatus` until approved, denied or expired.
4. Record decisions with the file, so the token never appears in a prompt:

   ```bash
   papyrus references approve --reference <record id> --on-behalf-of <person's sign-in email> \
     --agent <your name> --instruction "<the person's exact words>" --delegation-file <path>
   ```

   `--delegation-token` and `PAPYRUS_DELEGATION_TOKEN` still work.

`recordDelegatedCuration` refuses a delegation that is pending, denied or
unapproved (`not-approved`) and keeps every other check. A person can still
revoke an approved delegation at any time.

#### For the approve screen

All of these need a signed-in Newsroom editor, except the two the agent calls.

- `listCurationDelegations` (query) returns a list of `CurationDelegationResult`:
  `ok`, `delegationId`, `token` (always null here), `agentLabel`,
  `grantorLabel`, `expiresAt`, `revokedAt`, plus the new `state`
  (`pending|approved|denied|expired|revoked`), `userCode` (`XXXX-XXXX`, only
  while pending), `requestedHours`, `pendingExpiresAt`, `approvedAt`,
  `deniedAt`. Live pending requests from every agent are included; for a
  pending request `expiresAt` equals `pendingExpiresAt`.
- `approveCurationDelegation(userCode: String!)` (mutation) returns a
  `CurationDelegationResult` with `state: approved`. The code is accepted in
  any case, with or without the hyphen. Unknown, expired or already decided
  codes are refused.
- `denyCurationDelegation(userCode: String!)` (mutation) returns a
  `CurationDelegationResult` with `state: denied`.
- `revokeCurationDelegation(delegationId: ID!)` still revokes an approved
  delegation (and also works on a pending one).
- The agent's routes (an operator on AWS credentials, or an editor's CLI session
  on the CLI's own sign-in client, see below): `requestCurationDelegation(delegationId, tokenHash,
  agentLabel, hours)` returns `{ ok, delegationId, userCode, pendingExpiresAt,
  requestedHours }`; `getCurationDelegationStatus(delegationId)` returns
  `{ delegationId, state, expiresAt, grantorLabel }`. Neither returns a secret
  or hash.

### An agent on the signed-in CLI (no AWS login)

The routes above first worked only for an operator on AWS credentials. An agent that works in an
editor's own `papyrus login` session asks the same way, with no AWS login:

```bash
papyrus references request-delegation --agent Claude --hours 2 --wait
papyrus references approve --reference <record id> --on-behalf-of <person's sign-in email> \
  --agent Claude --instruction "<the person's exact words>" --delegation-file <path>
papyrus references set-stars --reference <record id> --stars 4 --on-behalf-of <person's sign-in email> \
  --agent Claude --instruction "<the person's exact words>" --delegation-file <path>
```

`references set-stars` records a star rating the person gave, with the rules of the Newsroom's own
rating (`setReferenceStars`, `reference_stars`): a whole number from 1 to 5, or `--stars clear` to
remove it, the newest rating wins, and it never changes the accept or reject. Like the other
mutation commands it writes unless you pass `--dry-run`; `--dry-run` and `--help` check the
arguments and send nothing. A relayed rating is filed as `<person> via <agent> (delegation <id>)`,
never as the person's own rating (`starRatedBy`).

**The person's approval stays the gate.** In this lane the agent's session is the editor's own, so
"who is signed in" cannot tell a request from an approval. What tells them apart is the Cognito
app client the session's token was issued to, which Cognito signs and a session cannot change:

| Caller | Ask, check status, relay | Approve, create, list | Deny, revoke |
| --- | --- | --- | --- |
| Operator on AWS credentials | yes | no | no |
| Editor or admin, token for the CLI's own client | yes | **no** | yes |
| Editor or admin, token for any other client (the Newsroom) | no | yes | yes |
| Anyone not an editor or admin | no | no | no |

Approving, creating and listing (which shows pending codes) refuse the CLI client's sessions, so
an agent cannot approve its own request, create an already approved delegation, or read someone
else's pending code. Denying and revoking only reduce what an agent may do, so they stay open to
the session that asked. The groups are checked in the schema rules and again in the handler.

The backend learns the CLI's client from `CURATION_CLI_CLIENT_ID`, which the site backend sets
only when the site signs the CLI in on its own client (`cliOnFederationClient`, see
[CLI login](cli-login.md#which-client)). **A site that has not done that refuses every
signed-in request** with a message naming the setting, because there the CLI and the Newsroom
share a client and a session could approve its own request. Operators on AWS credentials ask as
before. Turning the lane on is therefore a site setting plus the backend deploy that carries this
change; nothing about the Newsroom's own approval changes. The federation client is also the one
the site's server uses for Prospectus sign-in; a token from it is treated as a CLI session
(it can ask, not approve), which is the safe direction.

A token whose client cannot be read (no `aud` or `client_id`) is refused on the delegation routes. Direct
accepts, rejects and ratings are not affected: any editor or admin session may make them, whichever client
it came from (see the section above).

**About containment.** Delegation approval stops one session from approving its own request. It does not stop an editor-group session from writing some data
directly through the model API: `Item` (including a Story's `starRating`) is writable by the editor
and admin groups, whereas `Reference` is read-only to them (its votes and ratings are written only
by the Lambdas), so a Reference's curation and star fields are contained.

**Where delegations are stored matters.** They live in their own model, `CurationDelegationRecord`,
which only the Newsroom's function can write (the admin group can read it; no group, identity-pool
or public rule can create or change a row). They used to be a JSON attachment on a
`KnowledgeRawPayload` row, and the editor groups can write that model and attach files to it, so an
editor's session could have forged an approved delegation. Records in the old place are never read:
every delegation made before this change is simply unknown, and the agent asks again (a pending
request lasts only ten minutes, an approved one at most 72 hours). Do not move them back to a
model the editor groups can write. Other category-action routes that record a person's
decision under a name the caller supplies (`setReferenceQualityRating`, `decideReferenceLink`,
`reviewReferenceTopicLabel`, `reviewSteeringProposal`, `createReferenceNote`, `moveReferenceCorpus`)
are not gated against CLI sessions.

Expiry (72 hours at most, eight by default), the audit record (agent name, the approver, the
editor whose session asked), revocation and the checks of agent name, named person and token are
the same on both lanes. A delegation is stored in the site's own backend, so another site's
backend does not know it. A direct vote from a CLI session without a delegation is recorded as an
agent's vote (`curationActorKind: agent`), never as a person's label.

Only relay what the person actually said. If you are unsure, quote their words in
`--note` and ask. A delegation lets you record a human decision; it does not let
you decide.

Limit to know about: an agent with direct write access to the data models could
still write curation metadata itself. The delegation makes the honest path
verifiable, and the audit trail (delegation id, agent, grantor) lets a person
check it; removing direct write access to the Reference's curation fields is a separate
hardening step.

### Naming the section

An accept, direct or relayed, can also say which newsroom Section the Reference
belongs in:

```bash
papyrus references approve --reference <record id> --on-behalf-of <person's sign-in email> \
  --agent <your name> --instruction "<the person's exact words>" --section <newsroom section id>
papyrus references review-curation --reference <record id> --action accept --section <newsroom section id>
```

`reviewReferenceCuration` and `recordDelegatedCuration` take an optional
`sectionId`. It must be the id of an enabled `NewsroomSection`; an unknown or
disabled section is refused before anything is written, and a section on a
reject, reopen or archive is refused. The id is stored as `sectionId` in the
`curationSectionId` on the Reference beside `curationActorKind`. Only an accept that the signed-in
person made, or that the person delegated, counts as their section label.

### Changing only the section (`references set-section`)

To put an accepted Reference in a section, or move or clear it, without voting again (no repeated acceptance note):

```bash
papyrus references set-section --reference <lineage id> --section security [--agent <your name>] [--dry-run] [--json]
papyrus references set-section --reference <lineage id> --clear
```

It changes only `curationSectionId`, and records who and when in `curationSectionUpdatedBy` and `curationSectionUpdatedAt`. The acceptance (status, who voted and when, the note, the actor kind), the feedback and the star rating are not written, so the Cyclotron sees no new vote. `--section` takes a display name (`Security`), a slug (`security`) or the qualified form `machines-on-machines#security`; a name that is not an enabled section is an error that lists the accepted forms and the sections available, and nothing is written. A section can be set only on an accepted Reference; `--clear` works on any. Like the other commands it writes unless `--dry-run`, which reads the Reference and the sections, prints the change and sends nothing. A signed-in editor or admin session records the person (`<person> via cli (<agent>)`); an operator on `PAPYRUS_GRAPHQL_AUTH=iam` is recorded as `Papyrus operator (<role session>)`, never by a name it sends. The writer is the `setReferenceSection` mutation (`amplify/functions/category-action`, editor and admin groups, and IAM principals by IAM policy like the other curation mutations).

The MCP tool `reference_set_section` (`lineageId`, `section` or `clear`, optional `dryRun`) is the same operation: `src/papyrus_content/reference_section.py` holds the one definition (`set_reference_section`), the CLI prints it as a line or `--json`, and the tool returns that JSON. Its `TOOLS` and `DESCRIPTIONS` entries have the shape of the MCP server's tables, as the image operations do; the server (the `feature/PPY-2bc3e8-authenticated-mcp` branch) adds them with `TOOLS.update(...)` when it merges. A change of section moves the Reference on the home page and on the videos grouping through the Reference stream, which already watches `curationSectionId` ([home page, Freshness](home-page.md#freshness)). Specs: `features_backend/reference-set-section.feature`, `scripts/test-reference-section.ts` (the function), `src/papyrus_content/reference_section_test.py`; `npm run test:reference-section`. Deploy: the backend (a new mutation and two optional `Reference` fields); no IAM change, no index change.
