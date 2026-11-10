# Agent CLI guide

<!-- guide:top -->

**Agents: read this file, or run `papyrus guide` (5.101+; on older versions read this file) (`papyrus guide --list` lists the tasks, `papyrus guide find` prints one section).** It is written so you never have to guess a flag.

> **Maintainer note.** Whoever builds or changes a `papyrus` command updates the recipe for it in this file in the same pull request. The drift test (`procedures/newsroom/tests/test_agent_cli_guide.py`, specified by `features_backend/agent-cli-guide.feature`) parses every fenced `papyrus ...` command below and fails CI when a command is not in the CLI's route table or when a `--flag` is not in that command's `--help` usage. Commands that are still in an open pull request sit in fences marked `pending` and in the test's `PENDING` list; remove both marks when the pull request merges. The usage text `--help` prints comes from the table in `src/papyrus/operator/command_usage.py`: change an entry in the same pull request when you change a command's flags (the drift test checks every `--flag` used here against it). After editing, copy the file to `src/papyrus_content/data/agent-cli-guide.md` (the copy `papyrus guide` prints; the same test fails when the two differ). Verified against Papyrus 5.100.0 on 2026-11-09 with a signed-in editor on `newsroom.machines-on-machines.anth.us`.

Every recipe says its **lane** (editor, operator or both) and the **version** it needs. Commands print tab-separated lines; a JSON `papyrus_request_summary` line on standard error is the request meter and can be ignored.

## Orientation
<!-- guide:orientation -->

### Version, sign-in and site
**Lane:** both. **Version:** any.

```sh
papyrus --version
papyrus login newsroom.machines-on-machines.anth.us
papyrus auth status
export PAPYRUS_SITE=newsroom.machines-on-machines.anth.us
export PAPYRUS_GRAPHQL_TIMEOUT_SECONDS=300
```

- `papyrus login SITE` opens a browser once (Google sign-in only). `papyrus whoami` renews and prints every signed-in site's session as JSON; a site you are not signed in to prints `No session; run papyrus login SITE`.
- `papyrus auth status` and `papyrus whoami` always list every signed-in site, whatever `PAPYRUS_SITE` says.
- Choose the site for a command with `PAPYRUS_SITE=host`, or a leading `papyrus --site host <group> <command>` (only the leading position; a trailing `--site` means something else for several commands). With several sites signed in and none chosen, the CLI lists them and stops; it never guesses.
- A signed-in editor needs no `amplify_outputs.json`, no `AWS_PROFILE` and no endpoint variable. Run from any folder outside a Papyrus checkout (inside one, the root guard stops a different install; `--allow-cross-root` overrides it on purpose).
- Set `PAPYRUS_GRAPHQL_TIMEOUT_SECONDS=300` before any write. The default is 30 seconds, and a write that times out has an unknown outcome (see the safe re-run rule below).

### The two lanes
| | Editor lane (signed in with `papyrus login`) | Operator lane (AWS credentials, `PAPYRUS_GRAPHQL_AUTH=iam`) |
| --- | --- | --- |
| Who | A person or an agent working inside a person's session | Operators and scheduled jobs |
| Needs | `papyrus login SITE` | `AWS_PROFILE`, an `amplify_outputs.json` or `PAPYRUS_GRAPHQL_ENDPOINT` |
| Can | Search and read; file pending References; tag and link; create Stories, save versions, publish; re-render pages the site's own function allows | Everything the editor can, plus model writes, procedures, knowledge runs, `retype`, `relations import-types`, local steering files |
| Cannot | Write models directly (concepts and links go through the site's routes); `references prepare-catalog`; `references suggest-links` (no vector index ARN); relation updates | Nothing by design, so use `--dry-run` first |
| Attribution | Records the person who signed in, with `via cli` | Needs `--author-label NAME` on several commands |

A failed user session never falls back to the operator lane. If a command says it needs AWS credentials, it is operator-only.

### Write by default, and which commands cannot dry-run
Mutation commands **write unless you pass `--dry-run`**. `--apply` is rejected ("no longer accepts --apply"). `--help` never writes: it is answered before anything runs.

Commands that write with **no `--dry-run`** (their `--help` says `Writes: yes, immediately`): `papyrus ops relations import-types`, `papyrus knowledge concepts import-types`, `papyrus ops content rebuild`, `papyrus ops content upload-preview`, `papyrus ops content project` (only `--reconcile` takes `--dry-run`), `papyrus stories fire-triggers`, `papyrus editorial check-version` (it stores its result with the version), `papyrus ideas synthesize` (it files the ideas it makes), `papyrus references register`, `papyrus login` and `papyrus logout`. Never run one to see what it does. `--help` prints `Writes:` for every command; when it says `not stated`, assume the command writes immediately.

`papyrus ops content rerender --no-invalidate --dry-run` was seen to re-render the story's pages anyway on 5.100.0 (the flag is sent to the site's function, which acted on it). Preview a re-render with `papyrus ops content update-live --story LINEAGE --dry-run` instead.

### Timeouts and the safe re-run rule
A write that prints `timed out` or `The read operation timed out` has an **unknown outcome**. Re-run the same command: `references create-from-catalog` derives the Reference id from the canonical URL, so a source already recorded is returned unchanged and is not re-curated; links and stars are idempotent (the same link is reported, not duplicated). Do not change arguments between attempts. Do not re-run `stories create` blindly: it makes a new Story each time, so list first (`papyrus stories list --limit 5`).

### The relation vocabulary is closed
Only these names exist; never invent one:

| Relation | Used for |
| --- | --- |
| `see_also` | Story to Story or Story to accepted Reference (`stories link-story`) |
| `tagged_with` | Story or Reference to a concept (`stories link-concept`, `references link-concept`) |
| `uses_evidence` | Story to the Reference it uses (`stories link-reference`; roles `consulted`, `cited`, `based_on`) |

Reference-to-Reference links take a predicate (`related_to`, `cites`, `supports`, `contradicts`) and Reference-to-concept links made by `references link` use `related_to`, the legacy name of `tagged_with` (`stories check-links` reports it as "legacy: migrate").

### When in doubt
1. Add `--dry-run` if the usage shows it.
2. Read `papyrus <group> <command> --help` (it prints the flags, whether it writes, the lane).
3. Run `papyrus guide` or `papyrus guide TASK`.

## Find things
<!-- guide:find -->

### Search the knowledge base by words and meaning
**Lane:** editor. **Version:** 5.97+ (verified 5.100.0). Read only.

```sh
papyrus references search "plate reader stalking" --show all --limit 10
papyrus references search "plate reader stalking" --limit 10 --cursor CURSOR_FROM_PREVIOUS_PAGE
```

Prints `N References`, then one row per hit (id shortened with `...`, `unrated` or its stars, `Matched: title, link`, title) and `Next page: --cursor ...`. Use `--json` for full ids. `--show` is `unrated`, `rated` or `all` (default `all`).

### List References
**Lane:** both. **Version:** any. Read only.

```sh
papyrus references list --status pending --limit 10
papyrus references show REFERENCE_ID
```

`list` prints `backend=cloud corpusKey=KEY`, then `kind status id title corpus url` rows. `--status` is `pending`, `accepted` or `rejected`; `--order` defaults to `newest`. There is **no stars filter** on `references list` (use `references search`, or `stories list --min-stars`). `show` takes the record id (`...-v1`) or the lineage id.

### List and read Stories
**Lane:** both. **Version:** any. Read only.

```sh
papyrus stories list --stage reporting --limit 10
papyrus stories list --type post --min-stars 3 --sort stars --limit 10
papyrus stories show --story LINEAGE
papyrus stories versions --story LINEAGE
```

`list` prints `stories list LINEAGE stage section title stars source votes bucket type words published`. The first column is the lineage id every other `stories` command takes. `type` is `article`, `post` or `untyped`. `show` prints the headline, a `signals` line, each stage move, its References by lineage id and its agent notes; `--json` prints the Story and its related Stories only.

### Concepts
**Lane:** both. **Version:** 5.101+ for `search` and `related` (PR #1341); `entities list` any. Read only.

```sh
papyrus knowledge concepts search --list
papyrus knowledge concepts search "license plate" --limit 10
papyrus knowledge concepts related --concept "License plate readers" --limit 10
papyrus knowledge entities list --status accepted --limit 20
```

- `search --list` prints every accepted concept and needs no key. Free text searches by meaning and needs `OPENAI_API_KEY` set in your shell (a signed-in editor session does not carry one); name matches come first and duplicates are flagged.
- `related` lists the concepts near one: confirmed links, aliases, and concepts that appear together on published Stories and accepted References. It finds the concept the way `link-concept` does (exact name, alias, `#hashtag` or node key) and needs no key.
- `knowledge entities list` lists concepts with `--status generated` by default (141 on Machines on Machines); the concepts you can tag with are `--status accepted` (207 there). It cannot search by meaning; use `search`. It needs no `--actor`.

### Suggested links for a Story
**Lane:** both. **Version:** 5.101+ (PR #1341). Read only.

```sh
papyrus stories suggest-links --story LINEAGE --kinds articles,posts,references --limit 10
papyrus stories suggest-links --story LINEAGE --include-linked --json
```

Ranks published articles and posts and accepted References that share the Story's concepts (rare concepts count most), shows the shared concepts and the path, and prints the exact command that would link each one. Already linked items are left out unless `--include-linked`. It writes nothing: run the printed `stories link-story` command yourself.

### Suggested links for a Reference (operator only)
**Lane:** operator. **Version:** any.

```sh
papyrus references suggest-links --corpus-id knowledge-corpus-ai-ml-research --reference-id REFERENCE_ID --dry-run
```

Needs the vector index. Signed in it fails with `Missing PAPYRUS_S3_VECTOR_INDEX_ARN`: do not retry it as an editor; tag by hand with `references link-concept` after `knowledge concepts search`.

## File a Reference from URLs
<!-- guide:file-reference -->

The verified editor path for filing pending References. **Lane:** editor (works for the operator too). **Version:** 5.100.0. **Writes:** yes; `--dry-run` previews.

```sh
printf 'https://example.org/story-one\nhttps://example.org/story-two\n' > sources.txt
papyrus references make-catalog --input sources.txt --output catalog.json
```

`make-catalog` prints `references make-catalog COUNT catalog.json` and writes `{"schema_version": 1, "items": [...]}` with `source_uri`, `title` (null), `item_id` and **`id`**. The signed-in intake accepts **only** `source_uri`, `item_id`, `title`, `media_type` and `ingestion_rationale`, so edit the file: delete `id`, fill `title`, add `"media_type": "text/html"` and a one or two sentence `ingestion_rationale` saying why you are filing it. A finished item:

```json
{"schema_version": 1, "items": [{"source_uri": "https://example.org/story-one", "item_id": "url-ref-f989da592b8e65b5", "title": "A real title", "media_type": "text/html", "ingestion_rationale": "Primary filing for the plate-reader case."}]}
```

```sh
papyrus references create-from-catalog --catalog catalog.json --corpus-key ai-ml-research --status pending --dry-run
papyrus references create-from-catalog --catalog catalog.json --corpus-key ai-ml-research --status pending
papyrus references list --status pending --limit 10
```

- The dry run prints `references create-from-catalog intake user-session items=N status=pending` and `apply no (preview only; server authorization and deduplication not executed)`.
- The real run prints one `recorded N/M URL REFERENCE_ID pending` line per source, then `summary confirmed=N not-confirmed=M`. It sends one source per request because one source takes 6 to 12 seconds.
- `--corpus-key` is the **site's publication key** (`ai-ml-research` on Machines on Machines). It is not the corpus record id and not the site name. On 5.100.0 `knowledge-corpus-ai-ml-research` is also accepted, the flag may be omitted (the site's one canonical corpus is used), and a wrong key fails with `Requested publication bogus does not match the hosted canonical corpus ai-ml-research; publication binding mismatch.`
- `--status` must be `pending`; accept or reject with the review commands afterwards.
- If a source reports `timed out`, run the identical command again.
- Each Reference id looks like `reference-knowledge-corpus-ai-ml-research-url-<64 hex>-v1`. Within about five minutes the router captures the text and writes the summary and the prediction.
- `--ingestion-rationale TEXT` supplies one rationale for every item that has none (an item's own `ingestion_rationale` wins). Every item still needs a `title`: `Every source needs a title and ingestion rationale.` is the error when either is missing.
- Do **not** use `references prepare-catalog` signed in: it needs a local steering config and prints `Unknown --corpus-key: ai-ml-research`.

## Tag and link
<!-- guide:tag-and-link -->

### Tag a Reference or a Story with existing concepts
**Lane:** both. **Version:** 5.100.0. **Writes:** yes; `--dry-run` previews.

```sh
papyrus references link-concept --reference REFERENCE_ID --concept "License plate readers" --concept "Surveillance" --dry-run
papyrus references link-concept --reference REFERENCE_ID --concept "License plate readers"
papyrus stories link-concept --story LINEAGE --concept "License plate readers"
```

Edge: `tagged_with`. A concept is found by exact name, alias, `#hashtag` or node key; it **never creates one**. An unknown name lists the closest accepted concepts; a concept already tagged prints `exists` and writes nothing. A name that two concepts share (`prompt injection` is both `topic--prompt-injection` and `editor_concept--prompt-injection`) is refused: pass the node key. A concept with no public wiki page prints a `warning` line (the tag is kept; the page just shows no link until a page exists). Output row: `references link-concept REFERENCE NODEKEY NAME [no public page] dry run|write|exists`.

### Create a concept while linking the first Reference
**Lane:** editor. **Version:** 5.100.0. **Writes:** yes; `--dry-run` previews.

```sh
papyrus references link --reference REFERENCE_ID --concept "License plate readers" --create --display-name "License plate readers" --dry-run
```

This is the only way an editor makes a concept from the CLI; it links with the legacy `related_to`. For later References use `link-concept`. Without `--create` an unknown name stops with `No concept is named 'x'. Name an existing concept, or add --create to make it.`

### Link a Reference to another Reference
**Lane:** editor. **Version:** 5.100.0.

```sh
papyrus references link --reference REFERENCE_A --to-reference REFERENCE_B --predicate supports --note "Same case, second source" --dry-run
```

Predicates: `related_to`, `cites`, `supports`, `contradicts`. There is no command to update or remove a link; running it again with new words replaces nothing for References (see "Not built yet").

### Link two concepts
**Lane:** editor. **Version:** 5.100.0.

```sh
papyrus knowledge entities link --key CONCEPT_KEY --to OTHER_CONCEPT_KEY --note "Why they relate" --dry-run
```

### Link a Story to its References and to other Stories
**Lane:** both. **Version:** 5.100.0. **Writes:** yes; `--dry-run` previews.

```sh
papyrus stories link-reference --story LINEAGE --reference REFERENCE_ID --role cited --dry-run
papyrus stories link-reference --story LINEAGE --reference REFERENCE_ID --role consulted --note "Read, not used"
papyrus stories link-story --story LINEAGE --to OTHER_LINEAGE --note "Earlier coverage" --dry-run
papyrus stories link-story --story LINEAGE --reference REFERENCE_ID --note "Primary filing" --dry-run
```

Roles: `consulted`, `cited`, `based_on`. `stories create --reference ID` links `based_on` at creation. `link-story --reference` (see also) needs an **accepted** Reference: a pending one is refused and nothing is written. A link in either direction counts as the same link.

### Rate a Reference or a Story
**Lane:** editor. **Version:** 5.100.0.

```sh
papyrus references set-stars --reference REFERENCE_ID --stars 4 --agent "editor agent" --dry-run
papyrus stories set-stars --story LINEAGE --stars 4 --agent "editor agent" --dry-run
```

`--stars` is 1 to 5, `clear` for a Reference, `0` for a Story. The rating is recorded as the signed-in person's, with a note that it came through the CLI. It does not accept or reject.

## Write and move a Story
<!-- guide:write-story -->

### Create a Story
**Lane:** both. **Version:** 5.100.0. **Writes:** yes; `--dry-run` previews.

```sh
papyrus stories create --title "Headline" --section security --stage reporting --summary "One sentence." --reference REFERENCE_ID --dry-run
papyrus stories create --title "Headline" --section security --stage reporting --summary "One sentence." --reference REFERENCE_ID
```

Prints `stories create created ITEM_ID`, `stories create lineage LINEAGE` and one `based on` line per Reference, then the reminder of the next procedure step. **Run it once**: each run makes a new Story. The dry run prints one line and does not check that the `--reference` ids exist. `--stage` is `idea`, `assignment` or `reporting` (default `idea`); `--section` takes a section id, slug or name.

### Set the Story type (post or article)
**Lane:** editor. **Status:** not built. `stories create` has no `--type` and there is no `stories set-type` (board story PPY-b3032b). A Story with type `untyped` cannot be published. Interim route: open the newsroom story editor and choose the type, or start the Story from the Create Story button on the Reference card. Check the result with `papyrus stories show --story LINEAGE` (the `signals` line shows `type`).

### List the versions
**Lane:** both. **Version:** any. Read only.

```sh
papyrus stories versions --story LINEAGE
```

Prints `stories versions N state time author reason ITEM_ID` per version, newest first; the last column is the version id (`LINEAGE-vN`) that `ops content publish --id` takes.

### Save a version
**Lane:** both. **Version:** 5.100.0. **Writes:** yes; `--dry-run` previews.

```sh
papyrus stories save-version --story LINEAGE --body-file body.md --front-matter-file front.yaml --reason "First draft" --dry-run
papyrus stories save-version --story LINEAGE --body-file body.md --front-matter-file front.yaml --reason "First draft"
```

Front matter keys: `title`, `dek`, `blurb`, `author` (a human's name, only if a person worked on it), `drafting: {by: AI}` (without it the byline drops "various bots"), `imageAlt`, `citations:` with a key for every `[@key]` in the body, `image:` for the card picture. Quote date values. Signed in, the author is the person who signed in; `--author-label` is ignored (the operator lane requires it). `--stage STAGE` or `--advance` also moves the Story.

### Move a Story on the board
**Lane:** both. **Version:** 5.100.0.

```sh
papyrus stories move --story LINEAGE --stage copywriting --reason "Draft saved" --dry-run
papyrus stories set-slug --story LINEAGE --slug real-address --dry-run
```

`--stage published` changes only the board stage and prints a warning: **no page is published**. A Story with a placeholder slug such as `draft-security-47ecad5db5f6b10b` is refused at publish until `set-slug` gives it a real address.

## Publish and make it visible
<!-- guide:publish -->

### Publish a version
**Lane:** both. **Version:** 5.100.0. **Writes:** yes; `--dry-run` previews.

```sh
papyrus ops content publish --id LINEAGE-v3 --dry-run
papyrus ops content publish --id LINEAGE-v3 --verify
```

`--id` is the **version** item id (`LINEAGE-vN`, the lineage plus the version `stories show` prints), not the lineage id (`content publish failed [not-found]: No item LINEAGE`). Or pass `--slug SLUG [--section KEY]`. Stops with `[placeholder-slug]` for a placeholder address, `checklist-open` while procedure steps are open, and refuses an untyped Story. Close the checklist honestly first (see Checks).

### Make the new page visible
**Lane:** both. **Version:** 5.100.0.

**Nothing purges the CDN when you publish.** The edge keeps a page for about five minutes (`s-maxage`), and batch pages refresh on their own. Purge only the one page being discussed with the editor, never batches, and never more than needed (a call over 25 paths is refused without `--force-paths N`; over 5 paths is a dry run until `--run`).

```sh
papyrus ops content update-live --story LINEAGE --dry-run
papyrus ops content update-live --story LINEAGE --run
papyrus ops content rerender --story LINEAGE --no-invalidate
papyrus ops content refresh --path /articles/slug/ --dry-run
papyrus ops content inspect-page --story LINEAGE
```

- `update-live` on a Story that was never published stops with `site_update_live: refused [not_found]: No published Story with lineage id ...`; publish first.
- `update-live` re-projects one Story, purges exactly its pages and the index pages that list it (12 exact paths for a typical article) and checks the live page shows the new version. The dry run prints `site_update_live: ok (dry run: nothing written or invalidated)`, the pages and `invalidation: ok (dry-run), 12 paths`.
- `rerender --no-invalidate` rebuilds the pages from the deployed hooks and **does not purge**; use it after link writes when the edge may wait five minutes. Once PR #1344 merges the link commands (`link-story`, `link-concept`, `link-reference`) re-render the published Stories whose page changed by themselves (never purging, a failure is only a warning, at most 20 per command) and `--no-rerender` skips that (the recipe at the end of this section).
- `refresh --path PATH` purges exact pages (both URL forms and the Markdown twin) and nothing else. Never `/*`.
- `inspect-page` is read only: the record, the stored page and what the edge serves, with one verdict.

After PR #1344 merges (pending until then; remove the `pending` mark and the `--no-rerender` entry in the drift test's `PENDING` list):

```sh pending
papyrus stories link-story --story LINEAGE --to OTHER_LINEAGE --note "Earlier coverage" --no-rerender
```

Until then run the `rerender` command above by hand after you link.

## Checks
<!-- guide:checks -->

### Check a draft before publishing
**Lane:** both. **Version:** 5.100.0. Read only unless noted.

```sh
papyrus editorial check-version --item LINEAGE-v3
papyrus stories lens-check --story LINEAGE --static web
papyrus stories check-links --story LINEAGE
papyrus references check-links --reference REFERENCE_ID
papyrus stories next --story LINEAGE
papyrus stories step --story LINEAGE --step copy_edit --state done --note "Checked against the house rules" --agent "editor agent" --dry-run
```

- `check-version` runs the editorial rules on a saved version and stores the result with it. `lens-check` prints `finding LENS RULE STATE ...` rows; four problems must be fixed before a lens step can close (image without alt text, third-party image without credit, video without title or credit, Markdown copy that differs from the source). `--static` is the site's web directory (default `PAPYRUS_SITE_STATIC_DIR`).
- `check-links` lists links and tags that are not the official shape (`legacy: migrate`, `concept has no public page`, `state not current`). Read only; fixing is out of scope.
- `stories next` prints each procedure step with its state, then what is next. There is no `stories checklist`: the checklist is `next` (read) and `step` (write). A skipped or not-applicable step needs `--reason`; a review step needs `--note` with the findings; use honest notes.

## Ideas
<!-- guide:ideas -->

### Digest recent References and synthesize ideas
**Lane:** both in the code (`ideas` accepts a `papyrus login` session); `synthesize` needs a model key (`OPENAI_API_KEY`) and files the ideas it makes, with no `--dry-run`. Not run on the editor lane. **Version:** 5.100.0.

```sh
papyrus ideas digest --publication ai-ml-research --since 7d
papyrus ideas synthesize --publication ai-ml-research --since 7d --max 5
```

Both group by section and Cyclotron label, not by concept cluster or Reference link, and `synthesize` needs a model key, so an editor without one cannot run it. Until cluster-based idea generation exists, look at `references search` results and concept tags by hand.

## Troubleshooting
<!-- guide:troubleshooting -->

| Exact text | Cause | Fix |
| --- | --- | --- |
| `usage: papyrus knowledge query [-h]` | Old CLI printed nothing else | Upgrade; `papyrus knowledge query --help` now prints the real usage |
| `User-session intake accepts source_uri, item_id, title, media_type and ingestion_rationale only.` | The catalog still has the `id` field `make-catalog` writes, or another extra field | Delete `id` (and anything else) from every item |
| `Every source needs a title and ingestion rationale.` | `make-catalog` leaves `title` null and writes no rationale | Fill `title` and `ingestion_rationale` |
| `Unknown --corpus-key: ai-ml-research` | `references prepare-catalog` reads a local steering file | Do not use `prepare-catalog` signed in; go straight to `create-from-catalog` |
| `Requested publication X does not match the hosted canonical corpus ai-ml-research; publication binding mismatch.` | Wrong `--corpus-key` | Use the site's publication key, or omit the flag |
| `User-session catalog intake supports --status pending only` | `--status accepted` signed in | File pending, then review |
| `timed out` / `The read operation timed out` / `GraphQL request failed: The read operation timed out` | 30 second default timeout; outcome unknown | `export PAPYRUS_GRAPHQL_TIMEOUT_SECONDS=300`, then run the identical command again |
| `N of M sources were not confirmed` | Some creates timed out | Run the same command again; recorded sources are returned unchanged |
| `Missing PAPYRUS_S3_VECTOR_INDEX_ARN and custom.knowledgeQuery.s3VectorIndexArn` (then a Python traceback) | `references suggest-links` needs the vector index; an editor cannot reach it | Do not retry; use `stories suggest-links` and `knowledge concepts related`, then tag with `link-concept` (PPY-b3032b) |
| `Unsupported papyrus command: relations search` / `stories suggest-links` | The installed `papyrus` is older than 5.101 (concept names show as `relations`) | Upgrade; see `papyrus --version` |
| `'x' means more than one concept; name one by its node key: a, b` | `link-concept` with a name two concepts share | Pass the node key it lists |
| `Search by meaning needs an embedding key: OPENAI_API_KEY must be set in this shell and valid.` | Free-text `knowledge concepts search` embeds your words locally | Use `knowledge concepts search --list`, or `knowledge concepts related --concept NAME`, or export the key |
| `site_update_live: refused [not_found]: No published Story with lineage id ...` | The Story has no published version | `ops content publish` first |
| `Reference ... is pending. Nothing was written: only accepted References are shown on the page, so only those can be linked.` | `stories link-story --reference` with a pending Reference | Accept it first, or use `stories link-reference` |
| `No concept is named 'x'. Name an existing concept, or add --create to make it.` | `references link --concept` with an unknown name | Check `knowledge entities list`, or add `--create` |
| `No concept is named 'x'. Name an existing concept by its name, alias, #hashtag or node key.` | Same, from `link-concept` / `entities link` | `link-concept` never creates; use `references link --create` for the first Reference |
| `references link requires exactly one of --to-reference REF or --concept NAME.` | Both or neither given | Give one |
| `--predicate must be one of related_to, cites, supports, contradicts.` | Invented a predicate | Use the closed list |
| `A concept is linked with related_to.` | `--predicate` other than `related_to` with `--concept` | Drop `--predicate` |
| `references create-from-catalog no longer accepts --apply` (`... no longer accepts --apply. Writes now run by default; use --dry-run to preview.`) | Old habit | Remove `--apply` |
| `content publish failed [not-found]: No item LINEAGE` | `--id` takes the version id | Use `LINEAGE-vN` |
| `content publish failed [placeholder-slug]: ... still has the placeholder slug` | Story has a draft slug | `papyrus stories set-slug --story LINEAGE --slug ADDRESS` |
| Publish refuses an untyped Story | `type` is `untyped` | Set the type in the newsroom story editor (no CLI command yet) |
| `Not signed in to SITE; run papyrus login SITE` | Site not signed in | `papyrus login SITE` |
| `No session; run papyrus login SITE` | Expired or missing session | Sign in again |
| `papyrus-root-guard blocked cross-root invocation detected` | Running inside a Papyrus checkout with another install | Run from another folder, or `--allow-cross-root` on purpose |
| `Unsupported papyrus command: GROUP CMD` | Misspelled or unbuilt command | `papyrus GROUP --help` lists the commands |
| `N paths is over the cap of 25 paths per call` | Purge too wide | Narrow it; never force more than you need |
| `Sign-in needs local port 3001 ... already in use` | Another program on the login port | Stop it, log in again |
| `Missing amplify_outputs.json` / endpoint errors on the operator lane | Not signed in and no outputs file | Sign in, or run from a site checkout with the outputs file |

## Not authorized, not built yet
<!-- guide:not-built -->

Honest rough edges. Board story **PPY-b3032b** ("Editor-session rough edges from the Lamar Roman case") tracks the numbered items. Whoever builds one updates the recipe above and removes it from this list; the drift test fails if a flag changes.

| Rough edge | Today | Board |
| --- | --- | --- |
| `stories create --type article|post` and `stories set-type` | Type is set only in the newsroom editor; untyped Stories cannot publish | PPY-b3032b (1) |
| `make-catalog` output accepted as is; `prepare-catalog` signed in | Hand-edit the catalog; skip `prepare-catalog` | PPY-b3032b (2) |
| Longer default timeout or may-have-completed reporting | `PAPYRUS_GRAPHQL_TIMEOUT_SECONDS=300` and re-run | PPY-b3032b (3) |
| `references suggest-links` for editors; concept search without a local key | Operator only (`stories suggest-links` and `concepts related` cover editors; free-text `concepts search` needs `OPENAI_API_KEY` in the shell) | PPY-b3032b (4) |
| Searching `knowledge entities list` | Lists by status, no search; use `knowledge concepts search --list` | PPY-b3032b (5) |
| `references list --stars/--min-stars/--sort rank` | Use `references search` or `stories list` | PPY-b3032b (6) |
| Source kind (`Reference.type`) and same-story grouping | Only `references link` with `related_to`, `cites`, `supports`, `contradicts` | PPY-b3032b (7), PPY-0cd359 |
| `references link --create` makes concepts with the legacy `related_to` | Migration of legacy `related_to` concept tags to `tagged_with` is in flight; `check-links` reports the rest | PPY-b3032b (8) |
| `ideas digest` groups by concept cluster or Reference link | Groups by section and label | PPY-b3032b (9) |
| Editors updating relations | Editors can create relations, never update or remove them | PPY-b3032b |
| Re-render after link writes | Run `rerender --no-invalidate` yourself; PR #1344 (open) makes the link commands do it and adds `--no-rerender` | PR #1344 |
