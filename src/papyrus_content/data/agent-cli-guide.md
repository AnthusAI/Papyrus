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
- `papyrus today [--day YYYY-MM-DD] [--time-zone ZONE] [--runs] [--json]` answers "what did the system do today?": runs per responsibility by outcome (each a mark and words), the reasons for nothing to do, the agents that did not run, and cost. Read only; editors and admins. See `docs/automations.md`, "Today".
- `papyrus auth status` and `papyrus whoami` always list every signed-in site, whatever `PAPYRUS_SITE` says.
- Choose the site for a command with `PAPYRUS_SITE=host`, or a leading `papyrus --site host <group> <command>` (only the leading position; a trailing `--site` means something else for several commands). With several sites signed in and none chosen, the CLI lists them and stops; it never guesses.
- A signed-in editor needs no `amplify_outputs.json`, no `AWS_PROFILE` and no endpoint variable. Run from any folder outside a Papyrus checkout (inside one, the root guard stops a different install; `--allow-cross-root` overrides it on purpose).
- Set `PAPYRUS_GRAPHQL_TIMEOUT_SECONDS=300` before any write. The default is 30 seconds, and a write that times out has an unknown outcome (see the safe re-run rule below).

### The two lanes
| | Editor lane (signed in with `papyrus login`; the default) | Operator lane (AWS credentials, named with `papyrus --auth iam` or `PAPYRUS_GRAPHQL_AUTH=iam`) |
| --- | --- | --- |
| Who | A person or an agent working inside a person's session | Operators and scheduled jobs |
| Needs | `papyrus login SITE` | `AWS_PROFILE`, an `amplify_outputs.json` or `PAPYRUS_GRAPHQL_ENDPOINT` |
| Can | Search and read; file pending References; tag and link; create Stories, save versions, publish; re-render pages the site's own function allows | Everything the editor can, plus model writes, procedures, knowledge runs, `retype`, `relations import-types`, local steering files |
| Cannot | Write models directly (concepts and links go through the site's routes); `references prepare-catalog`; `references suggest-links` (no vector index ARN); relation updates | Nothing by design, so use `--dry-run` first |
| Attribution | Records the person who signed in, with `via cli` | Needs `--author-label NAME` on several commands |

The editor lane is the default. The operator lane is used only when named: `papyrus --auth iam <group> <command>` (leading, like `--site`), or `PAPYRUS_GRAPHQL_AUTH=iam` for a worker or a CI step. With no session and no lane named, a command stops before it reads or writes anything: `Not signed in: run papyrus login <site>. ...` (exit status 2); sign in, do not reach for AWS credentials. A missing or failed user session never falls back to the operator lane, and a CLI newer than the site's backend never switches lanes to get round what the backend lacks. If a command says it needs AWS credentials, it is operator-only.

When the operator lane fails with `Error when retrieving token from sso: Token has expired and refresh failed` while `aws sts get-caller-identity` works for the same profile, the CLI and the AWS library this tool uses keep their SSO tokens in different files under `~/.aws/sso/cache`. Fix it on the machine, in the profile, not in the tool: add `credential_process = aws configure export-credentials --profile <profile>` under `[profile <profile>]` in `~/.aws/config`, or sign in again with `aws sso login --profile <profile>`. The tool prints both when it hits this.

### Write by default, and which commands cannot dry-run
Mutation commands **write unless you pass `--dry-run`**. `--apply` is rejected ("no longer accepts --apply"). `--help` never writes: it is answered before anything runs.

Commands that write with **no `--dry-run`** (their `--help` says `Writes: yes, immediately`): `papyrus ops relations import-types`, `papyrus knowledge concepts import-types`, `papyrus ops content rebuild`, `papyrus ops content upload-preview`, `papyrus ops content project` (only `--reconcile` takes `--dry-run`), `papyrus stories fire-triggers`, `papyrus editorial check-version` (it stores its result with the version), `papyrus ideas synthesize` (it files the ideas it makes), `papyrus references register`, `papyrus login` and `papyrus logout`. Never run one to see what it does. `--help` prints `Writes:` for every command; when it says `not stated`, assume the command writes immediately.

`papyrus ops content rerender --no-invalidate --dry-run` was seen to re-render the story's pages anyway on 5.100.0 (the flag is sent to the site's function, which acted on it). Preview a re-render with `papyrus ops content update-live --story LINEAGE --dry-run` instead.

### Timeouts and the safe re-run rule
A write that prints `timed out` or `The read operation timed out` has an **unknown outcome**. Re-run the same command: `references create-from-catalog` derives the Reference id from the canonical URL, so a source already recorded is returned unchanged (printed as `already-existed` with its current status) and is not re-curated; links and stars are idempotent (the same link is reported, not duplicated). Do not change arguments between attempts. Do not re-run `stories create` blindly: it makes a new Story each time, so list first (`papyrus stories list --limit 5`).

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

### Read a Reference's captured text
**Lane:** both. **Version:** next release after 5.101 (PR for `references text`). Read only.

```sh
papyrus references text --reference LINEAGE_OR_ID --limit 5000
papyrus references text --reference LINEAGE_OR_ID --offset 5000 --limit 5000
papyrus references text --reference LINEAGE_OR_ID --limit 0 --json
```

Prints `reference`, `url`, `source` (how it was captured, or `edited by editor`), `captured-at`, `total-characters`, `offset` and `returned`, `truncated`, any `note:` completeness warnings, `next: --offset N` (or `end of text`), then `---` and the text slice. **Read the captured text instead of fetching the page again.** The default slice is 20000 characters; `--limit 0` reads to the end; `--json` prints the same facts with `text`, `nextOffset` and `flags`. `truncated: yes` means the capture itself was cut: the reader takes about 400 KB of a page's HTML (PDFs up to 8 MB, a larger one fails as `too_large`), so a very long filing or a script-heavy page can arrive incomplete. When it is `yes`, or a `note:` says the text stops mid-sentence, do not rely on the end of the text: use the SEC JSON endpoints below, or ask for the page to be pasted. Exit status 1 and `No captured text is stored` mean nothing was captured (a block page, a 403, or the router has not run yet: wait about five minutes after filing).

### List and read Stories
**Lane:** both. **Version:** any. Read only.

```sh
papyrus stories list --stage reporting --limit 10
papyrus stories list --type post --min-stars 3 --sort stars --limit 10
papyrus stories show --story LINEAGE
papyrus stories versions --story LINEAGE
```

`list` prints every Story of the stage, drafts included (the Stories board shows the same ones), one line per Story, newest change first, then `stories list N of TOTAL`: `--limit` (default 50) prints the first N, so when TOTAL is larger than N, raise `--limit`. Each line is `stories list LINEAGE stage section title stars source votes bucket type words published`. The first column is the lineage id every other `stories` command takes. `type` is `article`, `post` or `untyped`. `show` prints the headline, a `signals` line, each stage move, its References by lineage id and its agent notes; `--json` prints the Story and its related Stories only.

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
- The real run prints one line per source, then `summary created=N already-existed=M not-confirmed=K`. A source this run created prints `created N/M URL REFERENCE_ID pending`. A URL already recorded in the corpus prints `already-existed N/M URL REFERENCE_ID status=<current status> (existing; requested pending not applied)`: the Reference keeps whatever status it has (an accepted one stays accepted), and `--status` is never applied to it. Check the line before you treat a source as newly filed. A backend older than the CLI cannot say which it was, and the line is `outcome-unknown` instead. It sends one source per request because one source takes 6 to 12 seconds.
- `--corpus-key` is the **site's publication key** (`ai-ml-research` on Machines on Machines). It is not the corpus record id and not the site name. On 5.100.0 `knowledge-corpus-ai-ml-research` is also accepted, the flag may be omitted (the site's one canonical corpus is used), and a wrong key fails with `Requested publication bogus does not match the hosted canonical corpus ai-ml-research; publication binding mismatch.`
- `--status` must be `pending`; accept or reject with the review commands afterwards.
- If a source reports `timed out`, run the identical command again.
- Each Reference id looks like `reference-knowledge-corpus-ai-ml-research-url-<64 hex>-v1`. Within about five minutes the router captures the text and writes the summary and the prediction.
- `--ingestion-rationale TEXT` supplies one rationale for every item that has none (an item's own `ingestion_rationale` wins). Every item still needs a `title`: `Every source needs a title and ingestion rationale.` is the error when either is missing.
- Capture can fail quietly: a site that refuses the request (`blocked`, `http_4xx`) leaves no text and no summary, and a script-heavy page can be cut. Check with `papyrus references text --reference ID` before you rely on a Reference.
- **SEC filings (sec.gov):** EDGAR refuses anonymous automated requests (`Your Request Originates from an Undeclared Automated Tool`). Its rule is a declared `User-Agent` that names the requester and a contact. Never invent an address and never put a real one in a file you commit. Ask the person for a contact, or use the one configured for the site. Prefer the SEC's structured endpoints for deal terms and financials: `https://data.sec.gov/submissions/CIK##########.json` (the filing list) and `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` (reported values), sent with that declared `User-Agent`, over reading a 300,000-character 10-K page. A filing page captured by the router is cut at about 400 KB of HTML, before the notes to the financial statements.
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

### Add an entity with its aliases, and merge a duplicate (operators)
**Lane:** operator (`--auth iam`). **Version:** the release after 5.100. **Writes:** yes; `--dry-run` previews.

```sh
papyrus knowledge entities add --kind organization --name "National Transportation Safety Board" --alias NTSB --alias "The NTSB" --actor ai --dry-run
papyrus knowledge entities duplicates --kind person
papyrus knowledge entities merge --from person--musk --into person--elon-musk --actor ai --dry-run
```

`add` creates the accepted entity or finds it, adds every `--alias`, and refuses a name that duplicates an accepted entity of the kind (it names the entity to use). When a name is also the name of an entity of another kind, or of a concept, the command tags the entity and the ones it shares the name with with the **Disambiguation** concept, in code, so do not tag by hand. `duplicates` only reads: it lists the pairs the duplicate rules catch and the `merge` command for each. `merge` supersedes the duplicate (`--from`), keeps its name and aliases on the entity that stays (`--into`) and moves its item mentions and relations; afterwards run `knowledge entities registry`, `knowledge snapshot`, then `knowledge wiki sync` (the duplicate's page is left as it is: the sync never takes a page down). The knowledge run also asks the duplicate rules before it makes or accepts an entity: a candidate that is only another spelling is linked to the entity it duplicates and its name becomes an alias; one that only looks like a duplicate is held back with a proposal for a person.

### Link a Story to its References and to other Stories
**Lane:** both. **Version:** 5.100.0. **Writes:** yes; `--dry-run` previews.

```sh
papyrus stories link-reference --story LINEAGE --reference REFERENCE_ID --role cited --citation-key lemley2026 --dry-run
papyrus stories link-reference --story LINEAGE --reference REFERENCE_ID --role consulted --note "Read, not used"
papyrus stories link-story --story LINEAGE --to OTHER_LINEAGE --note "Earlier coverage" --dry-run
papyrus stories link-story --story LINEAGE --reference REFERENCE_ID --note "Primary filing" --dry-run
```

Roles: `consulted`, `cited`, `based_on`. `--citation-key KEY` stores the key on the link: `stories show` lists it beside the Reference, and the story-writing drafts cite the Reference by it. Give it when you link a Reference the body cites, using the key the body's citation uses; without it the link carries no key (`stories show` leaves the column empty) and the drafts make one from the Reference's lineage id. `stories create --reference ID` links `based_on` at creation. `link-story --reference` (see also) needs an **accepted** Reference: a pending one is refused and nothing is written. A link in either direction counts as the same link.

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

Prints `stories create created ITEM_ID`, `stories create lineage LINEAGE`, `stories create console ...` rows (show the editor that link: see below) and one `based on` line per Reference, then the reminder of the next procedure step. **Run it once**: each run makes a new Story. With `--with-assignment` it also opens a `reporting.candidate` Assignment (the Story's `--type` is never the Assignment's type). The `--reference` ids are attached first, so a failed Assignment never drops them; if the Assignment fails the command exits non-zero and prints `Story created (lineage ...), references attached: N, assignment NOT created: REASON` with the command to retry. The dry run prints one line and does not check that the `--reference` ids exist. `--stage` is `idea`, `assignment` or `reporting` (default `idea`); `--section` takes a section id, slug or name.

### Set the Story type (post or article)
**Lane:** both. **Version:** 5.101.0. **Writes:** yes; `--dry-run` previews.

```sh
papyrus stories create --title "Headline" --type post --section security --stage reporting --summary "One sentence." --dry-run
papyrus stories set-type --story LINEAGE --type article --dry-run
```

`stories create --type TYPE` sets the type at creation; without it the Story gets the site's default type, and the command warns when that is `untyped`, which cannot be published. `stories set-type` changes the type of a Story that is not published yet; a published Story is refused, because its page address depends on its type. The type is checked against the site's list when the CLI runs from the site checkout (or `PAPYRUS_SITE_STATIC_DIR` is set); otherwise it prints a note that the name was not checked. Check the result with `papyrus stories show --story LINEAGE` (the `signals` line shows `type`).

### List the versions
**Lane:** both. **Version:** any. Read only.

```sh
papyrus stories versions --story LINEAGE
```

Prints `stories versions N state time author reason ITEM_ID` per version, newest first; the last column is the version id (`LINEAGE-vN`) that `ops content publish --id` takes.

### Pull the stored text
**Lane:** both. **Version:** next release. Read only: it writes two local files and nothing to the Story.

```sh
papyrus stories pull --story LINEAGE --body-file body.md --front-matter-file front.yaml
papyrus stories pull --story LINEAGE --version 2 --body-file old-body.md --front-matter-file old-front.yaml
```

Writes the stored body and front matter of the **current** version (the one `stories show` calls current), or with `--version N` of that exact immutable version (`stories versions` lists the numbers). Edit from these files, never from the live page or its Markdown twin: those have rewritten picture paths and no citation data. The files are exactly what `stories save-version --body-file --front-matter-file` takes back, and a picture path in them is the stored path, which a save without `--images` keeps. Saving them unchanged still makes a new version (`save-version` never skips a save) whose text equals the one pulled. A Story with no stored front matter gets an empty front matter file. It prints `stories pull LINEAGE version N ITEM_ID state body FILE front matter FILE` (`--json` prints the same facts as JSON). An unknown Story or version is an error and writes no file. Do not reach into `papyrus_content` internals to read a version.

### Save a version
**Lane:** both. **Version:** 5.100.0. **Writes:** yes; `--dry-run` previews.

```sh
papyrus stories save-version --story LINEAGE --body-file body.md --front-matter-file front.yaml --reason "First draft" --dry-run
papyrus stories save-version --story LINEAGE --body-file body.md --front-matter-file front.yaml --reason "First draft"
```

Front matter keys: `title`, `dek`, `blurb`, `author` (a human's name, only if a person worked on it, or a pen name where the site's byline policy says so), `drafting: {by: AI}` (without it the byline drops "various bots"), `imageAlt`, `citations:` with a key for every `[@key]` in the body, `image:` for the card picture. Quote date values. Signed in, the author is the person who signed in; `--author-label` is ignored (the operator lane requires it). A figure from `papyrus figures render` saved with `--images` but without its `.dark.png` prints a `figure-light-only` warning; the site's `requireDarkFigures` setting (`papyrus design-system`), `--require-dark-figures` or `PAPYRUS_REQUIRE_DARK_FIGURES=1` refuses it instead (`PAPYRUS_REQUIRE_DARK_FIGURES=0` overrides the setting). `--stage STAGE` or `--advance` also moves the Story. It also prints the version's measurements and the change from the version before it, and stores them with the version (see "Measure a draft or a story"). It prints `stories save-version console story URL`: **show the editor that link** (the exact version) after every save, before asking for approval (see "Show the editor the console link").

### The dek is stored as the Item's `deck`
The story's dek is the front matter key **`dek`** (the canonical spelling; write it in every new version). Saving a version derives the Item's `deck` column, which feeds, the newsroom context pack, announcements, reference curation, boards and the published row read, from the front matter with one rule: `dek`, else `deck`, `standfirst`, `description` (the first that is not blank). Never write the column on its own, and do not put two of those keys in one story's front matter. A story saved before this rule can carry an older `deck`: `papyrus stories decks` re-derives it (see "Bring every `deck` to the story's dek").

### Write the dek and the blurb differently
The `dek` and the `blurb` are **intentionally different** fields. Write both, and never copy one into the other.

- **`blurb`**: a short summary for index pages and cards. It appears out of context, so it must **stand alone**: a reader who has not seen the headline or the article should still understand it.
- **`dek`** (the subtitle): read on the article page **as part of the article**, under the headline and above the opening paragraph. It must read smoothly with the headline and the opening, and must not repeat either.

Before and after, for a Story headed "Board refuses the merger":

```yaml
# Wrong: one sentence pasted into both fields
dek: The board of Acme Corp refused the merger with Beta Ltd on Tuesday.
blurb: The board of Acme Corp refused the merger with Beta Ltd on Tuesday.

# Right: the blurb stands alone, the dek continues from the headline
dek: Directors said the price undervalued the company, and a second offer is already being discussed.
blurb: Acme Corp's board refused Beta Ltd's merger offer on Tuesday, saying the price undervalued the company.
```

The dek leaves out "Acme Corp's board" because the headline has just said it; the blurb needs it because it may be the only text a reader sees.

**A difference between the dek and the blurb is expected. A reviewer or proofreader must not report it as an inconsistency or an error.** The one defect is an identical copy: `papyrus stories lens-check` raises a concern on check P2 when the dek and the blurb are word for word the same.

### Move a Story on the board
**Lane:** both. **Version:** 5.100.0.

```sh
papyrus stories move --story LINEAGE --stage copywriting --reason "Draft saved" --dry-run
papyrus stories set-slug --story LINEAGE --slug real-address --dry-run
```

`--stage published` changes only the board stage and prints a warning: **no page is published**. A Story with a placeholder slug such as `draft-security-47ecad5db5f6b10b` is refused at publish until `set-slug` gives it a real address.

### Show the editor the console link (required)
**Lane:** both. **Version:** 5.101.0 and later for `papyrus links` and the `console` rows; the console address must be known. Read only.

**This is a required step.** Whenever you create a Story, save a version of one, or materially change one (or file or curate a Reference or Concept) for the editor, show the editor the console link to that exact item before you ask for anything, and certainly before you ask to publish. They review the draft in the web console, not on a production page.

```sh
papyrus stories save-version --story LINEAGE --body-file body.md --reason "First draft"
# prints: stories  save-version  console  story        https://.../articles/LINEAGE-v3      (the exact version you saved)
#         stories  save-version  console  story-board  https://.../articles?open=contentItem%3ALINEAGE  (latest, with the checklist)
papyrus links --story LINEAGE --version 3 --reference REFERENCE_ID --concept "Concept name"
```

Tell the editor, for example: `Draft v3 is ready to review: <story link> (built from the saved version id; I have not opened it).` Rules:

- Give the `story` link (the exact VERSION id) for a draft you wrote. Give the `story-board` (drawer, lineage) link only to mean "the latest version".
- `stories create`, `stories save-version` and `stories show` print the rows; `references show` prints a `console:` line. For a Concept, an Assignment or a review item run `papyrus links` (`--concept`, `--assignment`, `--review`). Every id is checked against the site first.
- If the row says `unavailable`, the site has not published its console address: say so, and ask for it; pass it with `--console-url` or `PAPYRUS_CONSOLE_URL`. Never guess an address, and never write a link by hand.
- Say honestly whether you opened the link. A link built from an id is not a link you tested.
- The checklist has no address of its own: it is a panel in the drawer. Addresses, and what each does with a wrong id: `docs/console-links.md`.

## Publish and make it visible
<!-- guide:publish -->

### Publish a version
**Lane:** both. **Version:** 5.100.0. **Writes:** yes; `--dry-run` previews.

```sh
papyrus ops content publish --id LINEAGE-v3 --dry-run
papyrus ops content publish --id LINEAGE-v3 --verify
papyrus ops content publish --id A-v1 --id B-v1 --id C-v1   # a batch (signed-in lane): one page build for all of them, one hold of the projection lease
```

`--id` is the **version** item id (`LINEAGE-vN`, the lineage plus the version `stories show` prints), not the lineage id (`content publish failed [not-found]: No item LINEAGE`). Or pass `--slug SLUG [--section KEY]`. Stops with `[placeholder-slug]` for a placeholder address, `checklist-open` while procedure steps are open, and refuses an untyped Story. Close the checklist honestly first (see Checks).

### Retire a Story and redirect its address
**Lane:** both. **Writes:** yes; `--dry-run` previews. Not released yet: it ships with the next Papyrus release.

Use it when two Stories become one article: the Story that goes away keeps working for readers.

```sh
papyrus stories retire --story LINEAGE --redirect-to TARGET_LINEAGE --dry-run
papyrus stories retire --story LINEAGE --redirect-to TARGET_LINEAGE
papyrus stories retire --story LINEAGE --undo
```

The dry run lists each redirect as the public address a reader uses, from the site's projector, so it needs the site's settings (`PAPYRUS_SITE_PROJECTOR`, or `--static-dir DIR` with `projection.json`); without them the command refuses before writing anything. It reads only the Story's own versions and the target's published version, not the whole site, so the list is what will be redirected except any address another live Story has since taken over (the projection leaves that one out).

It removes any schedule the Story has first (a scheduled publish would bring it back), unpublishes the Story, moves it to the `retired` stage (every version stays) and has the site redirect every address the Story was served at (current address, aliases, earlier slugs and type folders, the `.md` twin) permanently to the target's address; if the target changes address later the redirects follow. The Story leaves listings, the sitemap, feeds, public data and the cross-story boilerplate check. The command prints the pages written and the exact paths purged; it never purges more than the site's cap. It refuses a target that is missing, unpublished, the Story itself or retired. `--undo` publishes the retired version again and removes the redirects. A site that requires approval to publish restores from the console. The page work runs as a background job the command follows (the same job status as a publish), so it ends with the pages written, or with `still-running` and the command to check again, never with a timeout for work that went on; it reports a failure only when the job fails. Against a backend that predates this it fails at once and says to deploy one that includes PPY-f171b4.

Retiring also takes back what was announced about the Story (`withdrew` lines): every Announcement that is now only about retired Stories is withdrawn, Delivery by Delivery, as `papyrus announcements withdraw` does. A Delivery that has not gone is stopped. A post that already went on X is deleted by the site's own X channel, which this command line does not hold, so its line says `NOT withdrawn` and names the Delivery; it stays sent until the site's own stack withdraws it. `--undo` withdraws nothing.

### Schedule a Story to publish later
**Lane:** editor. **Writes:** yes; `--dry-run` checks and writes nothing. Needs the site's `publication.timeZone` (a site without it answers `scheduling-off`). Not released yet: it ships with the next Papyrus release.

Pin the Story's newest version to a time. At that time the site publishes exactly that version, once, by the normal publish path; the Story keeps its first publication date and the version records "scheduled by" you.

```sh
papyrus stories schedule --story LINEAGE --at '2026-11-13 09:00' --dry-run
papyrus stories schedule --story LINEAGE --at '2026-11-13 09:00'
papyrus stories schedule --story LINEAGE --clear
papyrus stories schedule-list --from '2026-11-09 00:00' --to '2026-11-15 23:59'
papyrus stories schedule-list --story LINEAGE --state overdue
papyrus stories schedule-suggest --story LINEAGE
```

A time without an offset is read in the publication's time zone and stored as a UTC instant; `2026-11-13T14:00:00Z` or `2026-11-13T09:00:00-05:00` is exact. A wall-clock time that does not exist there (the spring-forward gap) is refused (`nonexistent-time`); one that happens twice (fall back) is refused with both choices (`ambiguous-time`): type it again with the offset. A time that has passed is refused. A Story has one schedule; scheduling again moves it, and `--clear` removes it. Only the newest version can be scheduled. If a newer version is saved first, nothing is published: the schedule becomes `blocked` ("A newer version was saved after this was scheduled. Schedule it again.") and the site's editors get a flag in the Notification Center. Publishing the Story now, taking it down or retiring it removes its schedule. `schedule-list` shows each schedule's state: `scheduled`, `publishing`, `blocked`, or `overdue` (the time passed and it has not published: publish it now or schedule it again). `stories show` adds a `schedule` line (UTC time). The MCP tools are `stories_schedule` and `stories_schedule_list`, the same operations. Design and states: `docs/scheduled-publishing.md`.

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
- `rerender` is a job the CLI follows to the end: exit 0 done, 1 failed, 5 `STILL RUNNING, not failed` (the wait, `PAPYRUS_PROJECTION_TIMEOUT_SECONDS`, ran out) or `OUTCOME NOT KNOWN, not failed` (the start request got no answer). Never read exit 5 as failure and never start a second one: run the `rerender ... --status` command the output prints, which asks once where the job stands. It needs a backend with the async re-render handling (PPY-4611d5).
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
papyrus editorial check --draft body.md --story LINEAGE
papyrus editorial check-version --item LINEAGE-v3
papyrus stories lens-check --story LINEAGE --static web
papyrus stories check-links --story LINEAGE
papyrus references check-links --reference REFERENCE_ID
papyrus stories next --story LINEAGE
papyrus stories step --story LINEAGE --step copy_edit --state done --note "Checked against the house rules" --agent "editor agent" --dry-run
```

- Illustration (step `illustration`, required for the Story types that need a cover, articles by default): it closes by itself when the current version has a stored cover (no approval is required on any site; a person's approval is metadata in the front matter `coverImage` record (`approvedBy`), never a credit line, and an `Approved by NAME` statement in an image credit is dropped at render; generated covers get no credit line and third-party ones keep theirs), with its dark picture where the site requires one. `stories step --step illustration --state done` is refused unless the records prove it; publishing refuses a covered type without it. A person (not an agent) can record an exception: `stories step --story LINEAGE --step illustration --state skipped --reason "WHY"`. See `docs/story-procedure.md`, The Illustration step.
- Rated (step `rated`, only for a site that turns on the design-system setting `publishRequiresRating`, off by default; to check a site, run `papyrus design-system show` and look for it under settings, or run `papyrus stories next --story LINEAGE` and read the `rated` step: `not_applicable` means the site has not turned the setting on): it closes by itself when the current version has an editor's star rating of 1 to 5 recorded by a person (`papyrus stories set-stars --story LINEAGE --stars N`; 0 clears it and a model's prediction never counts). `stories step --step rated --state done` is refused unless the rating proves it, and it cannot be skipped or marked not applicable. Publishing and republishing refuse an unrated Story and name the command; a new version keeps its rating, and a Story already published stays published. See `docs/story-procedure.md`, The Rated step.
- `editorial check --draft FILE` checks a body before it is saved and runs every check a saved version gets, including the cross-story boilerplate check (a passage of 12 or more words that another story on the site also has), so there is no need to save a version to learn about it. Pass `--story LINEAGE` (lineage id or slug) when the draft revises an existing story, so that story's own saved version is not reported as another story; without it the draft is compared with every story. `--pack FILE` checks against a policy file instead of the site, and a policy file has no stories, so the boilerplate check cannot run with it: the output's `notRun` list then names `cross-story-boilerplate` and the reason (`notRun` is an empty list otherwise). `editorial suggest --draft` takes the same `--story`.
- `editorial languages` shows how the site serves its languages (public, URL prefix and slug policy of each, defaults marked). `--enable es-419[,zh-Hans]` starts writing in a language (checked against the languages Humanus has a pack for, stored in Humanus's spelling, never public, its starter policy packs imported) and prints what it did and the next commands; `--disable TAG` stops, and is refused for the primary language and for a language with translations; both honour `--dry-run`, change nothing already as asked, and work on the editor and operator lanes. A new language still needs its writing and glossary overlays (`papyrus guidelines save --kind writing|glossary --language TAG`) before it translates well. `--set-public es-419` makes a language public (the primary always is), `--set-prefix es-419=es` and `--set-slug es-419=primary` set one language's value, and `--dry-run` shows the result without writing. It writes by default and refuses what the projection would refuse before it writes. See [multilingual serving](multilingual-serving.md).
- `check-version` runs the editorial rules on a saved version and stores the result with it. `lens-check` prints `finding LENS RULE STATE ...` rows; four problems must be fixed before a lens step can close (image without alt text, third-party image without credit, video without title or credit, Markdown copy that differs from the source). A local picture with no credit counts as ours and passes the credit check (leave credit off for a generated picture; `credit="Generated."` still works but is not needed); only a remote address, the stock cover record and a Reference's picture need a credit. `--static` is the site's web directory (default `PAPYRUS_SITE_STATIC_DIR`); `--no-network` skips the share-picture fetch.
- Social review (`--lens social`, step `review_social`): `lens-check` fetches the Story's planned share picture (check C4) and reports its absolute HTTPS address, status, Content-Type, format, size and shape. A built address is never a pass. JPEG or PNG at least 600x315 passes; WebP, AVIF or GIF, a small or oddly shaped picture, a missing, invalid or non-image picture, or a Content-Type that does not match the file is a warning; a picture that could not be requested (no network, `--no-network`, site without a public address) is `Could not check`, which means not verified. For cross-platform use make a JPEG or PNG share rendition (about 1200x630) and keep WebP/AVIF for the page; do not pad or upscale a small image without saying so in the note. Then read title, description and picture together for relevance, legibility, alt text and misleading context. The `--note` of `stories step --step review_social` must record the tested URL, format, dimensions, result, and any platform uncertainty (a passing check says the file looks compatible, not that a platform displayed it). The share picture comes from front matter `image`, then `cover`, then `ogImage`, then `thumbnail`, so `ogImage` is only a fallback and a different share picture needs `image` itself, which also becomes the card picture.
- After publishing, fetch the live page and check that `og:image` and `twitter:image` are the tested address, then fetch that address publicly (status 200, image Content-Type). Report a stale CDN or a platform's own preview cache separately; do not assume a platform shows the card.
- `check-links` lists links and tags that are not the official shape (`legacy: migrate`, `concept has no public page`, `state not current`). Read only; fixing is out of scope.
- `stories next` is the one answer about what remains: a `status` line (`complete`, `ready`, `blocked` or `stale`, and how many steps remain), a `step` line per step, a `version` line per checklist step, and a `remaining` line per step still to do, in order (`next` is the first). The Story's stored checklist decides each state; the records only add a `hint`. A review lens or the copy edit recorded against an earlier version reads `STALE: recorded against vN, story is now vM` and remains until you record it again for the current version. `13/13` and `status complete` mean nothing remains. `--json` has the same fields. There is no `stories checklist`: the checklist is `next` (read) and `step` (write). A skipped or not-applicable step needs `--reason`; a review step needs `--note` with the findings; use honest notes.

### Measure a draft or a story
**Lane:** both. **Version:** the first release after 5.127.0. Read only.

```sh
papyrus stories measure --story LINEAGE
papyrus stories measure --story LINEAGE --body-file body.md --front-matter-file front.yaml
papyrus stories measure --body-file body.md --language en
papyrus stories measure --story LINEAGE --json
```

- Plain numbers about the text, all computed by Humanus (Papyrus counts nothing itself), so they work before anything is saved. `size` is words (characters for `zh-Hans`) and reading minutes; `structure` is sections, paragraphs, the longest paragraph and sentence, and whether the headline (the title), dek and blurb in the front matter are present and how long; `sourcing` is links and citations, how many per 500 units, and the share of paragraphs with none; `change` is units added, removed and rewritten and the share of the text changed.
- `--story` alone measures the current saved version against the one before it. `--body-file` measures a draft; with `--story` it is compared with the story's current version and takes its language and front matter from the story (unless you pass `--language` or `--front-matter-file`). A draft with no `--story` needs `--language`: text is never read as a guessed language.
- `stories save-version` prints the same rows for the version it saved, with the change from the version it replaced, and stores them with the version record (`metadata.measurements`, with the Humanus version that computed them). A `--dry-run` save prints only its usual plan and measures nothing.
- The numbers are guidance for judging a piece before and after an edit. There are no limits: nothing is refused, blocked or required because of a number, so do not pad, cut or add links only to move one.

### Check the stage head index (operators)
**Lane:** both. **Version:** the release after 5.101.0. **Writes:** only with `--apply`; a dry run otherwise.

```sh
papyrus stories head-index
papyrus stories head-index --stage published
papyrus stories head-index --apply --rate 5
```

- Each Story has one row in the head stage index (`headStageKey`, docs/plans/story-head-stage-index.md). `head-index` reads the old stage index once, prints one `set` or `remove` line per row it would change, `muddled` lines for Stories with more than one live version (fix those with `stories repair-versions --story LINEAGE`), and a summary: `rows read`, `stories`, `heads to set`, `keys to remove`, `already right`, `muddled`, `no head`, `superseded with key`.
- Unlike most commands it is a **dry run unless `--apply`**. A dry run with `heads to set 0` and `keys to remove 0` is the health check. `--apply` writes only rows that differ, keeps each row's own `updatedAt`, never writes a superseded version, and writes at most `--rate` a second (default 5); a second run writes nothing.
- On a site whose data API has no `headStageKey` yet the dry run counts every Story as needing it and `--apply` refuses: the site needs the backend deploy that adds the index first, and that deploy and the `--apply` run each need Ryan's approval.

### Translate a published Story (editors)
**Lane:** both for `--dry-run` and `--automation`; the operator lane (`--auth iam`) to run it here. **Version:** the release after 5.112.1. **Writes:** yes, unless `--dry-run`.

```sh
papyrus stories localize --story LINEAGE --language zh-Hans --dry-run
papyrus stories localize --story LINEAGE --language es-419 --openai-key-parameter SSM_PARAMETER
papyrus stories localize --story LINEAGE --language es-419 --automation SITE.story-localize
```

- Without `--automation` the run happens in this process and needs the operator lane (lead with `papyrus --auth iam`) and a model key (`OPENAI_API_KEY` or `--openai-key-parameter`); the command waits and prints the run's id, cost and outcome; through `--automation`, follow the run in the automation's history (`automations runs`).

- Writes the translation request (`LocalizationRequest`, one per Story and language: the newest published source version) and runs the site's registered translation procedure for it: in this process on the operator lane, or through the site's automation with `--automation`. (The procedure's inputs are snake_case: `ceiling_usd`, `source_version`; register the procedure again after upgrading.) Setup: docs/story-translation-procedure.md. The run translates the changed blocks, checks every block against the English (parity rules and a bilingual judge) and with the language's policies, polishes until the findings stop shrinking, and saves an unpublished version of `LINEAGE--TAG` by AI. It never publishes.
- `--dry-run` prints the plan: blocks to translate and kept, the glossary terms the translator will be given, the predicted cost from the language's measured runs. It writes nothing.
- A held translation (a faithfulness error remains) raises a flag review request saying why. `--ceiling-usd` caps one run's model spend.

### Correct a published translation (editors)
**Lane:** either; the signed-in lane is the default. **Version:** the release after 5.112.1. **Writes:** yes, unless `--dry-run`.

```sh
papyrus stories correct-translation --story LINEAGE --language es-419 --edits-file edits.json --edited-by "Person Name" --reason "why" --dry-run
papyrus stories correct-translation --story LINEAGE --language es-419 --edits-file edits.json --edited-by "Person Name" --reason "why" [--approved-by "Person Name"] [--publish [--verify]]
```

- `edits.json` is a list: `[{"from": "old wording", "to": "new wording"}]`. The old wording must occur exactly once in the translation (add `"every": true` to change all occurrences); text that is not there, or an edit that would change a link, credit or other fixed part of a block, is refused and nothing is saved.
- Saves a new version of `LINEAGE--TAG` authored by `--edited-by`; each block it changes is the person's (owner `human`, pinned), so a later translation run keeps it exactly. The provenance records who edited, who applied it (the signed-in session), the reason, each block before and after, and `--approved-by` when given. The approver is metadata only and never appears on the page.
- Without `--publish` the version stays a draft; `--publish` publishes it as `papyrus ops content publish` does (a held translation still needs its review request answered), and `--verify` (only with `--publish`) waits for the public page. `--dry-run` prints each changed block before and after.
- Spec: `features_backend/translation-correction.feature`. Design: docs/story-translation-procedure.md, "A person's correction".

### Attach finished copy as a Story's translation (editors)
**Lane:** either; the signed-in lane is the default. **Version:** the release after 5.112.1. **Writes:** yes, unless `--dry-run`.

```sh
papyrus stories import-translation --story LINEAGE --language zh-Hans --body-file zh.md --front-matter-file zh.yaml --written-by "Person or agent" [--drafting-by-ai] --reason "why" --dry-run
papyrus stories import-translation --story LINEAGE --language zh-Hans --body-file zh.md --front-matter-file zh.yaml --written-by "Person or agent" --reason "why"
```

- For copy that was written separately and is finished (not a machine translation, not a correction). The Story must be published, in a language the site writes in, and not itself a translation. `--body-file` is Markdown with the English's blocks in the same order (separated by blank lines); the front matter is YAML with `title`, `dek` (or `deck`), and `blurb` and `imageAlt` when the English has them, in `--front-matter-file` or as a leading `---` block of the body file.
- Saves an unpublished new version of `LINEAGE--TAG`, paired with the published English version, authored by `--written-by`, which is also the front matter `author` of the version (`drafting: {by: AI}` only with `--drafting-by-ai`, when bots helped; the English Story's `author` and `drafting` are not inherited), so the site's standard byline reads "By NAME" or "By various bots and NAME" and is translated into the page's language like every byline; its provenance says the copy was written, not machine-generated. Every block is the writer's (owner `human`, pinned), so a later translation run keeps it exactly. No model is called: the parity and glossary rules and the language's copy-edit policies check each block and the whole body. An error-severity faithfulness finding holds the version (a flag review request a person answers with `papyrus reviews answer`); other findings are printed as advice.
- Refused, saving nothing: a language the site does not write in, an unpublished Story, a translation as the source, a copy whose blocks do not line up with the English's (the message gives both block counts and the first block where they stop matching), and a copy that changes a link target, address, citation, credit or a figure's settings (translate the words around them, and a figure's alt text and caption; keep the rest as the English has it).
- Writes the Story's translation request finished, so `papyrus stories localize --all` counts the language up to date and does not overwrite it. `--dry-run` prints the alignment, the findings and the version it would replace, and writes nothing. It never publishes: `papyrus ops content publish --id VERSION_ID`.
- Spec: `features_backend/translation-import.feature`. Design: docs/story-translation-procedure.md, "Finished copy written elsewhere".

### Translate a whole site, and translate on publish (operators)
**Lane:** the operator lane (`--auth iam`) to run or publish here; `--dry-run` and `--automation` (queue only) on either. **Version:** the release after 5.112.1. **Writes:** yes, unless `--dry-run`.

```sh
papyrus stories localize --all --language es-419 --dry-run
papyrus stories localize --all --language es-419 [--publish-clean] [--concurrency 3] [--openai-key-parameter SSM_PARAMETER]
papyrus stories localize --all --all-languages --publish-clean
papyrus stories localize --all --all-languages --updated-since 7d [--updated-before DATE] --dry-run
papyrus stories localize --all --language es-419 --automation SITE.story-localize [--publish-clean]
papyrus editorial languages --enable es-419 [--dry-run]
papyrus editorial languages --auto on --auto-automation SITE.story-localize [--auto-publish off]
papyrus editorial languages --auto off
```

- Run the first two on the operator lane (`papyrus --auth iam stories localize --all ...`). `--all` finds every published Story written in the primary language that has no up-to-date translation in the language (`--language TAG`, or every enabled language with `--all-languages`). A translation is up to date when its `LocalizationRequest` names this very text of the Story and its run finished (saved, held, unchanged or published); a held one waits for a person, not for the command. It reads the published summaries and the request records once each, never a table per Story, and a second run does only what remains (failed, stopped and never-started ones, and Stories published again).
- `--updated-since DATE` / `--updated-before DATE` (an ISO date or datetime in UTC, or `7d`, `36h`, `1w` counted back from now; start included, end excluded) keep only the Stories whose current published version was published in the range (`versionPublishedAt` of the published summary: no extra read; a Story with no such time is left out and counted). They apply to `--dry-run`, runs here, `--automation` queueing and `--publish-clean` alike, so `--publish-clean` publishes saved translations only for Stories in the range. Malformed dates are refused; an empty range says so and does nothing. They need `--all`.
- Without `--automation` each remaining Story runs in this process, `--concurrency` at a time (default 3), and prints one row: `saved`, `held`, `failed` or `up to date`, the Story, the language, the cost and the reason. A failed Story is its own row and the others go on; the command then exits non-zero and says to run it again. `--publish-clean` publishes, through the ordinary publish path, only the translations whose run saved cleanly (including ones saved earlier and never published) while their original is still published at that text: never a held one.
- With `--automation ID` nothing runs here: the requests are written `wanted` with the automation and `--publish-clean`'s choice, and the site's dispatcher starts them on the site's runner (needs the release's backend deployed). `--dry-run` predicts every remaining Story's cost from the procedure's measured runs of that language (a language with none has no prediction) and writes nothing.
- `papyrus editorial languages --auto on --auto-automation ID` makes a site translate every Story into every enabled language when it is published or republished (setting `languages.auto` = `{enabled, automation, publish}`; off by default; `--auto-publish off` leaves clean translations for a person to publish). Setup and behaviour: docs/story-translation-procedure.md, "Translating on publish".

### Publish a translation (editors)
**Lane:** both. **Version:** the release after 5.110.0. **Writes:** yes, unless `--dry-run`.

```sh
papyrus stories versions --story LINEAGE--es-419
papyrus ops content publish --id LINEAGE--es-419-v1 --dry-run
papyrus ops content publish --id LINEAGE--es-419-v1
```

- A translation is a Story of its own (`LINEAGE--TAG`) and a person publishes it with the ordinary publish command and the version id; nothing publishes it by itself (docs/story-translation-procedure.md, "Publishing a translation").
- It has no English checklist and no rating of its own. It is refused with `original-unpublished` unless its original is published, and with `translation-held` when the run held it (a faithfulness error remained) until a person answers the run's flag review request (`localize-...`, named in the refusal) with `approve` or `acknowledge`: an editor in the newsroom's Notification Center, or an operator with `papyrus reviews answer --id ID --decision approve` (docs/review-requests.md). A held translation never holds the English Story.
- Its page is at `/<prefix>/<its own address>/`, says in its own language that an AI translated it (with a link to the original) and lists the other languages as `hreflang`. `unpublish` takes it off; unpublishing the original takes every translation off the site until the original is published again.

### Bring every `deck` to the story's dek (operators)
**Lane:** both. **Writes:** yes, unless `--dry-run`.

```sh
papyrus stories decks --dry-run
papyrus stories decks
```

- It re-derives the `deck` column of every Item version and published row from the front matter that row holds (`dek`, else `deck`, `standfirst`, `description`) and writes only the rows whose stored value differs, with each row's own `updatedAt`. It never writes front matter. A row with no front matter (a checklist step, a guideline document) is left alone. It prints one line per row it would write and a summary per model (`rows read`, `rows to write`, `already right`, `without front matter`); a run with `rows to write 0` is the health check.
- You do not need to run it after a deploy: the post-deploy render runs the same code once per site, before it renders (marker `_papyrus/migrations/item-decks.json` in the site store).

### Give every Item row its language (operators)
**Lane:** both. **Version:** the release after 5.109.0. **Writes:** yes, unless `--dry-run`.

```sh
papyrus stories languages --dry-run
papyrus stories languages
```

- Every Item version carries `language` (a BCP 47 tag: `en`, `es-419`, `zh-Hans`) and `languageGroupId` (the primary Story's lineage; a localization is the sibling lineage `{primary}--{language}`). Writers set them from the release that adds them; `stories languages` writes them on the rows written before: the site's primary language and the row's own lineage as its group.
- It reads the version-state index once (no table scan) and each published row by its id, prints one line per row it would write and a summary per model (`rows read`, `rows to write`, `already right`), writes only missing fields with each row's own `updatedAt`, and never changes a language a row has. A run with `rows to write 0` is the health check.
- You do not need to run it after a deploy: the post-deploy render runs the same code first, once per site, before it renders (a marker in the site store records that it is done). Run it by hand only to check (`--dry-run`) or on a backend without the post-deploy render. A row written later without a language is still refused, by the projection and by the editorial checks; the deploy does not repair it.

### Backfill published dates (operators)
**Lane:** both. **Version:** the release after 5.101.0. **Writes:** only with `--apply`; a dry run otherwise.

```sh
papyrus stories backfill-published-dates
papyrus stories backfill-published-dates --apply --rate 5
```

- A Story's `publishedAt` is its first publication, carried to every later version, and `versionPublishedAt` / `versionPublishedBy` say when and by whom the served version went live (docs/site-hosting.md, "Published and updated dates"). The command moves Stories published before that change to the new meaning, using only what their versions recorded: the earliest version whose `changeReason` is `publish`, never later than the date the Story already has.
- It prints one `set` line per row it would change, an `unclear` line per Story whose first publication cannot be derived (a version was taken down, which overwrote its publish time, or no version recorded a publish) and a summary: `stories`, `rows to write`, `already right`, `unclear`. Unclear Stories keep their `publishedAt`; a person decides.
- It is a **dry run unless `--apply`**. `--apply` writes only rows that differ, keeps each row's own `updatedAt`, and writes at most `--rate` a second (default 5); a second run writes nothing. It needs the backend deploy that adds `versionPublishedAt` and `versionPublishedBy` to Item and PublishedItem first.

## Draw a figure
<!-- guide:figures -->

### Render a figure in light and dark
**Lane:** both (it reads the signed-in site's design system and writes only local picture files). **Version:** the release after 5.101.0.

A figure is a folder with `figure.svg` (colors as `{role}` names, type as `t-<role>` classes) and `figure.json` (the acceptance criteria, alt text and caption; no credit, since our own figures carry none). The skill `.agents/skills/figures` says when to draw and how to choose a form; no person's approval is needed unless the site opted in (`illustrationRequireApprovalCredit`); the rules are `papyrus figures rules` (the signed-in site's own text when it saved figure rules, otherwise the general rules; it says which on stderr; `--packaged` prints the general ones) and the shape library `papyrus figures primitives`. Both light and dark are mandatory: `render` always writes both from the one source.

```sh
papyrus figures rules
papyrus figures primitives
papyrus figures render ./search-nobody-sees --check-only
papyrus figures render ./search-nobody-sees --out ./pictures
papyrus figures render ./search-nobody-sees --design-system ./design-system --out ./pictures
papyrus figures render ./search-nobody-sees --neutral-default --json
papyrus figures directive ./search-nobody-sees
```

- With no `--design-system` and no `--neutral-default`, `render` draws with the design system the **signed-in site stores** (see "Read and publish the site's design system" below) and prints a `figures: using the site's stored design system` line on stderr. `--design-system DIR` overrides it with a folder: `mapping.json` (roles, canvas, fonts, tokens inline or `tokens_file`), the font files it names, and optional `examples/NAME/figure.svg` + `figure.json`. **A site with no design system:** pass `--neutral-default` (unbranded grays, this machine's own sans-serif, no logos) and tell the person you did. Never invent a brand. If the site stores none or cannot be read, the command refuses and says why; it does not fall back.
- It prints `SLUG: PROBLEM: ...` and `SLUG: note: ...` lines and `SLUG: ok` or `SLUG: FAILED`, and exits 1 when any figure fails. A problem in either theme fails the figure. `--json` prints the same as data. `--check-only` writes nothing.
- On success it writes `SLUG.png` (light), `SLUG.dark.png` (dark) and `SLUG.figure.json` (marks the pictures as a figure) next to the source, or into `--out` (one figure only). The pictures are twice the canvas size with the fonts in the pixels.
- It needs `pip install playwright` and either `playwright install chromium` or Google Chrome. Without them the command says so and stops; nothing else in the CLI needs it.
- `directive` prints the `::image{}` line for the Story from `figure.json`; put it in the body and save with `stories save-version --images ./pictures` (see "Save a version"). The checker cannot judge whether the figure makes sense: look at both pictures yourself. It prints no credit unless `figure.json` names a real `Source:`; `approved_by` is optional metadata.

### Localize a figure for a translation (optional)
**Lane:** both. Reads the Story and its translation; writes only the translation (`STORY--LANGUAGE`), and only with `--save` or `figures variant`. **Version:** the release after 5.117.0.

A translation shows the original's picture with its alt text and caption translated, and that is complete. Prefer figures that need no translation (figure rules, section 8). When a figure holds words and a language variant is worth it:

```sh
papyrus figures localize ./figures/hazard --story STORY --language es-419 --out ./figures
papyrus figures localize ./figures/hazard --story STORY --language es-419 --save --reason "Spanish labels"
papyrus figures variant --story STORY --language es-419 --original assets/story/hazard.png --light hazard-es.png --dark hazard-es.dark.png --reason "Spanish labels"
```

- `localize` translates only the SVG's `<text>` content, the alt text and the caption (the Story's glossary, register notes and Humanus checks; findings are printed as `note:` lines and never block), renders light and dark with the usual figure checks, and prints the `figures variant` command for the pictures; `--save --reason` stores them as the translation's variant in one go (`--dry-run` previews). A figure with no text says so and does nothing.
- `variant` is the manual path for any picture, rasters included: the files become the translation's picture in place of `--original` (the `src` on the original Story), with `--alt` and `--caption` when the words changed. Without `--dark`, a figure is refused where the site requires dark figures. The front matter records `imageVariants`, so a re-translation keeps it.
- `papyrus.story.localize` reports `imagesWithText`, the source's figures or cover that hold words and have no variant in that language: advice for an editor, never a hold.

### Read and publish the site's design system
**Lane:** both. `show` and `pull` read (`pull` writes only the local folder); `push` writes a new design system version unless `--dry-run`. **Version:** the release after 5.101.0.

A site's tokens, fonts, role mapping and worked examples are backend data, kept beside its mission and policy. An agent that can sign in to the site reads them; the site's repository publishes them at deploy.

```sh
papyrus design-system show
papyrus design-system show --version 2 --json
papyrus design-system pull ./design-system
papyrus design-system pull ./design-system --force
papyrus design-system push ./design-system --reason "New display font" --dry-run
papyrus design-system push ./design-system --reason "New display font"
```

- `show` prints the version, who saved it and why, the figure and type roles, the fonts, the worked examples and the site's figure settings, or says the site has no design system (then use `--neutral-default` and say so, or ask for one). `--version N` reads an older version; `--json` prints it as data.
- `pull DIR` writes the stored files back exactly as they were pushed (text verbatim, fonts as files, `settings.json` when set). `DIR` must be new or empty unless `--force`. The folder works as `figures render --design-system DIR`.
- `push DIR --reason TEXT` checks the folder first (every role present, a light and a dark value for every color, the fonts it names exist) and refuses one that cannot draw. An unchanged folder makes no version. A folder holds `mapping.json`, its tokens file, the fonts, `examples/NAME/figure.svg` + `figure.json`, and an optional `settings.json` such as `{"requireDarkFigures": true}`; a folder with no `settings.json` keeps the site's settings. Signed in, the author is the person; on the operator lane `--author-label` is required. `--dry-run` lists what would be stored and writes nothing. This is the command a site repository runs as part of its deploy.
- The site setting `requireDarkFigures` makes `stories save-version` refuse a figure with no dark picture (see "Save a version"). The editorial context pack points at the design system when the site has one.

## Guidelines
<!-- guide:guidelines -->

### Read, change and save a site's guidelines
**Lane:** editor (signed in with `papyrus login`). **Version:** the release after 5.101.0 that carries the guidelines door; a site gets it with its data API deploy, so `papyrus guidelines show` on a site not yet deployed answers `service_unavailable`. `show`, `resolve`, `diff` and `history` only read. `save` writes immediately unless you pass `--dry-run`, and only an admin may save.

A site keeps its guidelines as versioned documents: one per **kind** (`writing`, `image`, `video`) for the publication, and optionally one per section laid over it. An unknown kind is refused with the list of the kinds the site knows. Text lives in S3; every save makes a new version and the old ones stay. A save creates the version's row first (state `pending`, invisible to every read), attaches the files to it, and only then makes it current; if the upload fails, running the same save again finishes that version and nothing else is left over.

```sh
papyrus guidelines show --kind writing
papyrus guidelines show --kind writing --section security
papyrus guidelines resolve --kind writing --section security
papyrus guidelines resolve --kind writing --section security --language zh-Hans
papyrus guidelines history --kind writing
papyrus guidelines diff --kind writing --file ./writing.yml
papyrus guidelines save --kind writing --file ./writing.yml --reason "Narrowed the audience" --expected-current-version-id item-editorial-doctrine-writing-v1 --dry-run
papyrus guidelines save --kind writing --file ./writing.yml --reason "Narrowed the audience" --expected-current-version-id item-editorial-doctrine-writing-v1
papyrus guidelines save --kind video --file ./video.yml --reason "First video guidelines" --expected-current-version-id none
papyrus guidelines save --kind byline --file ./byline.yml --reason "Satire uses pen names" --expected-current-version-id none
papyrus guidelines save --kind procedure --file ./procedure.yml --reason "Our Story steps" --expected-current-version-id none
papyrus guidelines save --kind agent-instructions --file ./agents.yml --reason "Our agents' roles" --expected-current-version-id none
```

- `--language TAG` (writing and video) names a language overlay: only what is particular to that language (register notes, words to prefer and avoid, the locale's naming conventions, glossary entries), laid over the guidelines every language shares. `resolve --language` lays the language's overlays over the publication's and the section's and says which layer each field came from. An overlay cannot set binding rules. A language that offers a register (Spanish: `usted` or `tu`) takes it as the overlay's `register` field, which switches that register's checks on or off (`papyrus guidelines save --kind writing --language es-419` with `"register": "usted"`); the shared guidelines refuse it. See [editorial checks](editorial-checks.md).
- Some kinds are site rules, the publication's alone with no section layer (`byline`, `figure-rules`, `procedure` and `agent-instructions`; see [site rules](newsroom-context-packs.md#site-rules)); a site with no saved document gets the default named there.
- `show` prints the stored document and its `expectedCurrentVersionId`: pass that to `save` as `--expected-current-version-id`. A kind with nothing stored yet answers `not_found` with `expectedCurrentVersionId: none` in `details`: pass `none` for the first save. `--version N` reads an older version.
- `resolve` prints the effective document and `fieldSources` (which layer gave each field: the publication, the section, or locked by the publication) and `layers` (each layer's version and hash). A section with no document of its own resolves to the publication's. A site with no document of that kind resolves to nothing with the warning `<kind>_guidelines_missing`; that is not an error. Image guidelines are resolved for a Story and a use, with `papyrus images profile resolve`.
- `diff` and `save --dry-run` compare the file with what is stored, field by field, and list the binding-rule changes (`constraintChanges`); they save nothing. A dry run of `save` prints `result.preview` with the same diff.
- `save` takes the document whole (JSON or YAML) from `--file`; the document is validated and every problem is listed by field in `details.problems`. A document equal to the current one makes no version (`unchanged: true`). `--expected-current-version-id` must name the version you read: if someone saved since, the answer is `stale_version`; read again and apply your change to the new version.
- **Binding rules** (`constraints`) belong to the publication. Adding, changing or removing one needs an admin who is a person: with `PAPYRUS_ACTOR_KIND=agent` the answer is `human_required` and nothing is saved, even in an admin's session. An editor's `save` is `not_authorized`.
- `history` lists the versions newest first with who saved each, whether a person or an agent, when, and why.
- **Guideline files, checked offline.** A guideline can also be a folder with a `GUIDELINE.md`: flat front matter (`id`, `type: papyrus:Guideline`, `name` equal to the folder's name, `description`, `kind` writing, image or announcement, `scope` publication, `section/<id>` or `channel/<name>` such as `channel/x`, `channel/linkedin` or `channel/email`, `severity` error, warn or guidance, and optionally `language`, `avoid`, `prefer`, `pattern`, `maxLength`) and the prose as the body. Keys are flat, an unknown key or a nested value is refused, and the whole set is valid or refused. `papyrus guidelines check --dir guidelines/ [--scope channel/x] [--language es] FILE...` needs no site, sign-in or model: it reports listed words (whole words, any case), patterns and lengths, and lists every rule that needs judgement as `notCheckedOffline`, never guessing. The publication's guidelines always apply; `--scope` adds a section's or a channel's. `guidance` is never checked, `warn` is reported, and the exit status is 1 only when an `error` guideline finds something (2 when the guideline folders are refused). It reads and writes nothing. **Writing guidelines are stored as these files (schema version 2).** `papyrus guidelines save --kind writing --dir guidelines/ --reason TEXT --expected-current-version-id ID|none [--section KEY] [--language TAG] [--dry-run]` stores the folder as the next version of that kind and scope (a stale version is refused, as for any save); `papyrus guidelines export --kind writing --dir OUT [--section KEY] [--language TAG] [--version N]` writes the stored files back byte for byte; `diff --dir` lists the files that would be added, changed or removed. Every file of the set is for the lineage it is saved into: `scope` `publication` (or `section/<key>` for a section's set) and `language` the overlay's tag or none. A guideline with a fixed name is a **field**: the kebab-case name of a field of the writing document (`tone`, `voice-patterns`, `lexicon`, `glossary`, `headline`, `constraints`, `body-markus`, ...), severity `guidance`, and its value in the body (text, a `- ` list of sentences, or one fenced `json` block); `show` still prints those fields as the document, and the console (Administration, Policies, Writing guidelines) is a files editor: it lists the set, edits each file's front matter and body, adds and removes field files and rule files, shows each file's severity and derived check, and saves the whole set with `files`. Any other name is a **rule file**: `error` and `warn` ones each derive one editorial check (`guideline-<name>`), and `resolve` lists them as `guidelineFiles`, publication first, a section adding and never replacing one of the same name (`rule_file_shadowed`). A version saved before the conversion is history only (`legacy_version`); `papyrus guidelines convert [--apply]` converts a site's JSON documents once (a dry run unless `--apply`, an admin who is a person), and is removed once every site has been converted; see [the cutover](guidelines-files-cutover.md). A `pod check` for guideline files comes with the pod checker, which does not exist yet.
- **Applying a picture** (`papyrus images apply C --story L --use cover --alt "..." --expected-current-version-id V`). `--alt` is required and describes what the picture shows, written by someone who has seen it. Never copy the generation brief: it is an instruction to the image model ("No devils, horns..."), and alt text that is empty, equal to the brief or containing it is refused with `checks_failed`; the Story's `illustration` step stays open for a cover with such alt text. Apply leaves the picture `unreviewed` and opens a review request; `--reviewed` (a person says they looked) is the only way to `human-verified`, an agent that passes it gets `human_required`, and `images review --decision keep` is person-only. If you have not seen the picture, say so and let the review request carry it; do not invent alt text.
- `--kind image` runs the image profile operations (`papyrus images profile ...` keeps working). With `--section` it reads and saves that section's image document, the section layer `papyrus images profile resolve` lays over the profile; a section without one keeps using its old visual style and visual guidance fields.

## Announcements
<!-- guide:announcements -->

### Announce Stories on the publication's X account, safely
**Lane:** editor (signed in with `papyrus login`). **Version:** the release after 5.107.2 that carries the announcement models; a site gets it with its data API deploy. `where`, `recent`, `explain`, `dry-run`, `settings show` and `account status` only read (`dry-run` makes one model call to draft). `pause` and `resume` write at once, and so does `settings set`, which only a person may call (an agent gets `human_required`) and only an admin may save. Nothing posts until Caducus's `x` channel is deployed on the site.

A site announces a Story on its own X account once, automatically, when the Story's page goes live or its rating reaches the owner's bar (never below the quality floor, 3 stars by default; a five counts only when a person gave it). Only Stories are announced, never References. X is one channel of the Story's Announcement: its Delivery is made with the Announcement, or added to it when a later rating reaches the bar. The text is drafted from the Story's title, dek and summary under the site's writing guidelines and `announcement` rules, and goes through the automatic checks (length as X counts it, no invented mention or link, the editorial rule lane, and a fact check against the Story). A draft that fails is not sent: its Delivery is `Blocked: check failed` with the reason, one review request is raised for the Announcement, and the machine drafts it again only when the Story or the guidelines change. How much human review a Delivery gets is the announce rung of the agent policy (`papyrus announcements review`). Mode is Off (default), Dry run (builds and checks the exact post as `Dry run: not sent`, sends nothing, cost 0) or On. The owner sets a budget for each X billing cycle (no default) and X's price list with its date; announcements pause by themselves before passing the budget.

```sh
papyrus announcements account status                                             # mode, pause, spend against the budget, our post count this cycle, the budget suggestion
papyrus announcements account connect                                            # prints the newsroom page where the X account is connected (a browser step)
papyrus announcements blocked                                                    # the Stories that qualified and wait, each with its reason
papyrus announcements retry 'announcement-1#x#handle#g1'                         # a failed Delivery back to ready (a person only)
papyrus announcements settings show
papyrus announcements settings set --mode dry_run --min-stars 5 --story-types article --budget 10.00 --billing-cycle-day 1 --label-confirmed --input-file ./prices.json
papyrus announcements dry-run story-containment-note
papyrus announcements where story-containment-note
papyrus announcements recent
papyrus announcements explain --story story-containment-note
papyrus announcements explain --delivery 'announcement-1#x#handle#g1'   # the guideline layers and examples its draft read
papyrus announcements pause
papyrus announcements resume
papyrus announcements record-manual 'announcement-1#x#handle#g1' --url https://example.org/status/1
papyrus announcements correct 'announcement-1#x#handle#g1' --text 'A look at how slow water shapes stone, corrected.'
papyrus announcements withdraw 'announcement-1#x#handle#g1'                        # stop it, or take it back where the channel can: a post on X is deleted
papyrus announcements versions 'announcement-1#x#handle#g1'                       # who saved each version, which blocks are pinned; --version N shows its words
papyrus announcements draft 'announcement-1#x#handle#g1' --replaces 1 --text 'Slow water has landed.'   # the next version; name the version you read
papyrus announcements draft 'announcement-1#x#handle#g1' --candidate --text 'Another wording.'          # kept beside the draft, nothing changes
papyrus announcements candidate choose 'announcement-1#x#handle#g1' c1 --replaces 2
papyrus announcements pinned 'announcement-1#x#handle#g1' --replaces 2 --block 2 --unpin
papyrus announcements unlock 'announcement-1#x#handle#g1' --lock-at 2026-11-17T08:55:00Z   # after the lock time, so it can be edited again
papyrus announcements example 'announcement-1#x#handle#g1' --scope channel --reason 'Open with the verb.'   # a person says how far an edit reaches; no scope keeps it as a candidate
papyrus announcements preferred 'announcement-1#x#handle#g1' --replaces 1 --text 'Slow water has landed.' --scope channel   # how it should have read, after the send: teaches, sends nothing, changes no public text
```

- `prices.json` holds `{"prices": {"createPost": 0.015, "createPostWithUrl": 0.2, "deletePost": 0.01, "readPost": 0.005, "asOf": "2026-11-12"}}` copied from X's price list (docs.x.com/x-api/getting-started/pricing); `--input-file` is how an object is given. The site's `announcements` function checks every rule and refuses with the plain sentence (`settings_refused`); nothing is saved when one fails. `--billing-cycle-day` is the day of the month your X billing cycle starts: the budget is per cycle.
- `dry-run STORY` prints the exact post, its link with the UTM tags, its weight and every check, for any Story in any mode, and records nothing. `eligible` and `reason` say whether the rules would announce it.
- `where` and `recent` give one line for each Delivery in words and marks (`Dry run: not sent`, `Sending`, `Sent`, `Failed`, `Blocked: paused`, `Blocked: budget reached`, `Blocked: check failed`, `Withdrawn`), with its review, what it waits for, its attempts and the post address. The post text is in S3 (`versions` shows it).
- `pause` stops all posting and says who and when; `resume` puts back the X Deliveries that a pause or the budget held, ready for the next attempt (the site's own deliver side sends them). A pause the budget caused ends by itself when the budget has room (a new cycle, or a raised budget); a pause a person made, and one a broken X connection caused, never does.
- `correct DELIVERY --text TEXT` replaces a Delivery that went with a new one carrying the corrected text: the next generation, which `supersedes` the old one (the old says `superseded`). The text goes through the checks of a new Delivery (for an X post: length, no invented markup, and every claim against the Story) before anything is written; a failing check is `checks_failed` with every problem listed. The new Delivery keeps the old one's channel, account, mode and review, and goes through the worker as any Delivery does. Writes by default; `--dry-run` only checks the input. Refused as `constraint_conflict`, in plain words: a Delivery that never went (edit it instead), one with an attempt that has no answer yet (settle it first), one already corrected (by another person with other words, or any other correction), and one that is not the live generation. On X the old post is deleted as part of the correction where the site's own X channel makes it, and otherwise just before the corrected Delivery is sent, and the deletion cost is written on the old Delivery. Agents may correct from the `prepare` rung.
- `withdraw DELIVERY` takes a Delivery back and records who did. A Delivery that has not gone is stopped and nothing public changes; a post on X that went is deleted (a pause or the budget never blocks a deletion) and the Delivery keeps what the post cost in all; a sent email or a post a person made by hand cannot be taken back and is refused as `constraint_conflict` (send a correction). The Announcement is `withdrawn` once every Delivery is. A person always may; an agent (from the `prepare` rung) only when every Story the Announcement is about was retired, otherwise `human_required`. Deleting a post needs the site's own X channel: this command line says `service_unavailable` for a post that went. A Delivery a correction replaced is not withdrawn on its own.
- `record-manual DELIVERY --url URL` is for a Delivery whose mode is `manual` (no API or no budget): Papyrus drafts and checks the words, a person posts them by hand and pastes the address, and the Delivery becomes `sent` with that person's name in its attempt log. Only a person records it (an agent is told `human_required`), only once, only for a ready Delivery, and the address must be an `http://` or `https://` URL. No worker or channel ever sends a manual Delivery.
- Connecting the X account needs the browser (OAuth): the newsroom's Administration, Announcements page (`docs/x-announcements-setup.md`). The CLI never accepts a token or secret.

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
| `Not signed in: run papyrus login <site>` | No session and no lane named (the signed-in lane is the default) | `papyrus login SITE`; a job that runs as its own AWS role adds `papyrus --auth iam` (or `PAPYRUS_GRAPHQL_AUTH=iam`) |

## Not authorized, not built yet
<!-- guide:not-built -->

Honest rough edges. Board story **PPY-b3032b** ("Editor-session rough edges from the Lamar Roman case") tracks the numbered items. Whoever builds one updates the recipe above and removes it from this list; the drift test fails if a flag changes.

| Rough edge | Today | Board |
| --- | --- | --- |
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
