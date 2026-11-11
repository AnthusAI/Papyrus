"""One table of every `papyrus` command's usage: what `--help`, a bare invocation and `papyrus <group>` print.

Each entry is keyed by the words that name the command (`"stories create"`, `"ops content publish"`) and holds a one-line
summary, the usage (flags), the lane and what the command does to the site:

* lane: `editor` (works signed in with `papyrus login`), `operator` (needs AWS credentials, `PAPYRUS_GRAPHQL_AUTH=iam`),
  `both`, or `unverified` (an entry drafted from the code that nobody has run on the editor lane yet: treat it as operator-only).
* writes: `reads` (never writes), `local` (writes only a local file), `dry-run` (writes unless `--dry-run`), `writes` (writes immediately, no `--dry-run`),
  `unknown` (drafted from the code: assume it writes immediately when the usage shows no `--dry-run`).

Hand-written entries here win over the drafted ones in `command_usage_generated.py`. A command with no entry at all still prints a
usage block that says so. `procedures/newsroom/tests/test_agent_cli_guide.py` fails when a route has no usage, and it checks every
`--flag` that `docs/agent-cli-guide.md` uses against the usage text printed here, so change an entry when you change a command.
"""
from __future__ import annotations

from dataclasses import dataclass

from .command_usage_generated import GENERATED


@dataclass(frozen=True)
class Usage:
  path: str
  summary: str
  usage: str
  lane: str
  writes: str
  guide: str = ""

  def render(self) -> str:
    lines = [f"Usage: papyrus {self.path} {self.usage}".rstrip()]
    if self.summary:
      lines.append(f"  {self.summary}")
    lines.append(f"  Lane: {LANE_TEXT[self.lane]}")
    lines.append(f"  Writes: {WRITES_TEXT[self.writes]}")
    if self.guide:
      lines.append(f"  Recipe: papyrus guide {self.guide}")
    return "\n".join(lines)

  def one_line(self) -> str:
    return self.summary or f"({self.path})"


LANE_TEXT = {
  "editor": "editor (signed in with `papyrus login`); the operator lane (AWS credentials) is not needed.",
  "operator": "operator (AWS credentials, PAPYRUS_GRAPHQL_AUTH=iam). A signed-in editor session is refused.",
  "both": "both (signed-in editor with `papyrus login`, or operator with AWS credentials).",
  "unverified": "not verified on the signed-in editor lane; treat it as operator-only (AWS credentials).",
}
WRITES_TEXT = {
  "reads": "nothing; read only.",
  "dry-run": "yes, by default. Pass --dry-run to preview without writing.",
  "local": "nothing on a site; it writes only the local file named in its usage.",
  "writes": "yes, immediately. This command has NO --dry-run: do not run it to see what it does.",
  "apply": "only with --apply; without it, a dry run that writes nothing.",
  "unknown": "not stated for this command. If the usage shows no --dry-run, assume it writes immediately.",
}

_DRY = "dry-run"


def _e(path: str, summary: str, usage: str, lane: str, writes: str, guide: str = "") -> tuple[str, Usage]:
  return path, Usage(path, summary, usage, lane, writes, guide)


_ENTRIES = dict([
  # ---- references: find -------------------------------------------------------------------------------------------
  _e("references list", "List References, newest first (no stars filter: use `references search` or `stories list --min-stars`).",
     "[--status pending|accepted|rejected] [--order newest] [--limit N] [--corpus-key KEY] [--backend local|cloud]", "both", "reads", "find"),
  _e("references show", "Show one Reference by record id (`...-v1`) or lineage id.", "REFERENCE_ID [--backend local|cloud]", "both", "reads", "find"),
  _e("references text", "Read the captured text of a Reference (what the newsroom stored), a slice at a time, with its total length and whether the capture was cut.",
     "--reference ID|LINEAGE [--offset N] [--limit N] [--json]  (default --limit 20000 characters; --limit 0 reads to the end; exits 1 when nothing was captured)", "both", "reads", "find"),
  _e("references search", "Find References by words and meaning, rated or not, accepted or not.",
     "\"plain words\" [--show unrated|rated|all] [--limit N] [--cursor CURSOR] [--site HOST] [--json]", "editor", "reads", "find"),
  _e("references register", "Register a Reference in the local pod only (a developer's Kanbus pod; it does not touch a site).",
     "[--url URL] [--title TEXT] [--status pending] [--why TEXT] [--story ID] [--corpus-key KEY] [--id ID] [--backend local|cloud]", "operator", "writes", ""),
  # ---- references: file from URLs ---------------------------------------------------------------------------------
  _e("references make-catalog", "Turn a text file of URLs into a catalog.json (local file only; nothing is sent to a site).",
     "--input SOURCES_FILE --output CATALOG.json", "both", "local", "file-reference"),
  _e("references prepare-catalog", "Add steering-config defaults to a catalog. Needs a local steering config: do not use it signed in.",
     "--catalog CATALOG.json --output PREPARED.json --corpus-key KEY [--config STEERING.yml]", "operator", "local", "file-reference"),
  _e("references create-from-catalog", "File the catalog's sources as pending References. Safe to re-run: the id comes from the URL.",
     "--catalog CATALOG.json [--corpus-key PUBLICATION_KEY] [--status pending] [--ingestion-rationale TEXT] [--config STEERING.yml] [--dry-run]  "
     "(signed in, every item holds only source_uri, item_id, title, media_type, ingestion_rationale; set PAPYRUS_GRAPHQL_TIMEOUT_SECONDS=300)", "both", _DRY, "file-reference"),
  _e("references create-from-catalog-split", "Operator: split a catalog into research and news corpora, then register each.",
     "--catalog CATALOG.json [--config STEERING.yml] [--research-corpus-key KEY] [--news-corpus-key KEY] [--dry-run]", "operator", _DRY, ""),
  # ---- references: tag and link -----------------------------------------------------------------------------------
  _e("references link", "Link a Reference to another Reference or to a concept (the only way an editor makes a concept).",
     "--reference REF (--to-reference REF | --concept NAME [--create [--display-name TEXT]]) [--predicate related_to|cites|supports|contradicts] [--note TEXT] [--dry-run]  "
     "(a concept is linked with related_to only; no command updates or removes a link)", "editor", _DRY, "tag-and-link"),
  _e("references link-concept", "Tag a Reference with existing accepted concepts (edge tagged_with); never creates a concept.",
     "--reference ID|LINEAGE --concept NAME|#HASHTAG|NODEKEY [--concept ...] [--note TEXT] [--author-label NAME] [--dry-run] [--json]", "both", _DRY, "tag-and-link"),
  _e("references check-links", "List Reference concept tags that are not the official shape (legacy related_to, no public page).",
     "(--reference ID|LINEAGE | --corpus-id ID) [--json]", "both", "reads", "checks"),
  _e("references set-stars", "Rate a Reference as the signed-in person (a rating, not an accept or reject).",
     "--reference ID --stars 1-5|clear [--agent YOUR_NAME] [--dry-run]", "editor", _DRY, "tag-and-link"),
  _e("references set-section", "Set or clear the newsroom section of a Reference.",
     "--reference LINEAGE (--section NAME|SLUG|PUBLICATION#SLUG | --clear) [--agent YOUR_NAME] [--dry-run] [--json]", "both", _DRY, ""),
  _e("references approve", "Accept a pending Reference as the signed-in person.",
     "--reference ID [--agent YOUR_NAME] [--note TEXT] [--reason-code CODE] [--section SECTION_ID] [--dry-run]", "editor", _DRY, ""),
  _e("references reject", "Reject a Reference as the signed-in person; a rejection needs --note or --reason-code.",
     "--reference ID (--note TEXT | --reason-code CODE) [--agent YOUR_NAME] [--dry-run]", "editor", _DRY, ""),
  _e("references promote", "Promote a Reference into a section.", "REFERENCE --section SECTION [--actor-label NAME] [--dry-run]", "operator", _DRY, ""),
  _e("references suggest-links", "Suggest related References and concepts from the vector index, written as `suggested` links.",
     "--corpus-id ID --reference-id ID [--dry-run]  (needs PAPYRUS_S3_VECTOR_INDEX_ARN: fails signed in; editors use `stories suggest-links` and `knowledge concepts related`)",
     "operator", _DRY, "find"),
  _e("references auto-accept", "Run the router's automatic acceptance against one site.", "--site KEY [--corpus-key KEY] [--positive-label LABEL] [--precision P] [--latency-quantile Q] [--dry-run]", "operator", _DRY, ""),
  _e("references queue-predictions", "Queue a Cyclotron prediction for every pending Reference that has none.", "(--site KEY | --corpus-key KEY[,KEY...]) [--dry-run]", "operator", _DRY, ""),
  _e("references list-predictions", "List Cyclotron predictions for a corpus's References.", "--corpus-key KEY [--status STATUS] [--limit N] [--category-set ID] [--config STEERING.yml]", "operator", "reads", ""),
  # ---- stories ----------------------------------------------------------------------------------------------------
  _e("stories list", "List the Stories (each one's newest version, drafts included) of a stage, newest change first; the first column is the lineage id every other `stories` command takes.",
     "[--stage STAGE] [--section ID|SLUG|NAME] [--type article|post] [--stars N | --min-stars N | --max-stars N] [--sort updated|stars|rank] [--bucket day|week|none] [--limit N]",
     "both", "reads", "find"),
  _e("stories show", "Show one Story: headline, signals, stage moves, its References and notes.",
     "--story LINEAGE [--bucket day|week|none] [--json]", "both", "reads", "find"),
  _e("stories versions", "List a Story's saved versions (`LINEAGE-vN`); `ops content publish --id` takes one of these.", "--story LINEAGE", "both", "reads", "write-story"),
  _e("stories create", "Create a Story. It always makes a new one (list first). There is no --type: set post or article in the newsroom editor.",
     "--title TEXT [--section ID|SLUG|NAME] [--stage idea|assignment|reporting] [--summary TEXT] [--brief TEXT] [--reference REFERENCE_ID ...] [--with-assignment] [--actor-label NAME] [--dry-run]",
     "both", _DRY, "write-story"),
  _e("stories save-version", "Save the body and front matter as a new version (never publishes).",
     "--story LINEAGE --body-file FILE --reason TEXT [--front-matter-file FILE] [--author-label NAME] [--stage STAGE | --advance] [--outline] [--no-check] "
     "[--images DIR [--bucket B] [--identity-pool-id ID] [--require-dark-figures]] [--dry-run]  (signed in the author is the person; --author-label is required on the operator lane; a figure with no dark picture prints a figure-light-only warning, and the site's requireDarkFigures setting (design-system), --require-dark-figures or PAPYRUS_REQUIRE_DARK_FIGURES=1 refuses it; PAPYRUS_REQUIRE_DARK_FIGURES=0 overrides the setting)",
     "both", _DRY, "write-story"),
  _e("stories move", "Move a Story to a board stage. --stage published changes only the board stage and publishes no page.",
     "--story LINEAGE --stage STAGE [--reason TEXT] [--author-label NAME] [--dry-run]", "both", _DRY, "write-story"),
  _e("stories set-slug", "Give a Story a real address (a placeholder draft-<section>-<hash> slug cannot be published).",
     "--story LINEAGE|ID --slug lowercase-words [--force] [--no-trigger] [--dry-run]", "both", _DRY, "write-story"),
  _e("stories set-stars", "Rate a Story as the signed-in person.", "--story LINEAGE --stars 0-5 [--agent YOUR_NAME] [--dry-run]  (0 clears the rating)", "editor", _DRY, "tag-and-link"),
  _e("stories link-concept", "Tag a Story with existing accepted concepts (edge tagged_with); never creates a concept.",
     "--story LINEAGE|SLUG --concept NAME|#HASHTAG|NODEKEY [--concept ...] [--note TEXT] [--author-label NAME] [--dry-run] [--json]", "both", _DRY, "tag-and-link"),
  _e("stories link-story", "Link a Story to other Stories or to accepted References (edge see_also).",
     "--story LINEAGE|SLUG (--to LINEAGE|SLUG [--to ...] | --reference REFERENCE_ID [--reference ...]) [--note TEXT] [--author-label NAME] [--dry-run] [--json]  "
     "(a pending Reference is refused and nothing is written)", "both", _DRY, "tag-and-link"),
  _e("stories link-reference", "Link a Story to a Reference it used (edge uses_evidence), with a role.",
     "--story LINEAGE --reference REFERENCE_ID --role consulted|cited|based_on [--note TEXT] [--citation-key KEY] [--author-label NAME] [--dry-run]", "both", _DRY, "tag-and-link"),
  _e("stories suggest-links", "Rank related articles, posts and References for a Story, with the command that links each.",
     "--story LINEAGE|SLUG [--kinds articles,posts,references] [--limit N] [--min-score S] [--include-linked] [--json]", "both", "reads", "find"),
  _e("stories check-links", "List Story links and concept tags that are not the official shape. Read only; fixing is out of scope.",
     "[--story LINEAGE|SLUG] [--json]", "both", "reads", "checks"),
  _e("stories lens-check", "Check a Story's audience lenses (people, agents, search, social); fix the findings before closing a lens step.",
     "--story LINEAGE [--lens people|agents|search|social] [--static WEB_DIRECTORY] [--json]  (--static defaults to PAPYRUS_SITE_STATIC_DIR)", "both", "reads", "checks"),
  _e("stories next", "Print each procedure step with its state, then what is next (the checklist).", "--story LINEAGE [--json]", "both", "reads", "checks"),
  _e("stories step", "Set one checklist step's state, or add a note to it.",
     "--story LINEAGE --step KEY [--state done|skipped|not_applicable|open] [--reason TEXT] [--note TEXT] [--evidence TEXT] [--actor-label NAME] [--agent NAME] [--dry-run]  "
     "(skipped and not_applicable need --reason; a review step needs --note with the findings)", "both", _DRY, "checks"),
  _e("stories note", "Add a person's note to a Story.",
     "--story LINEAGE (--body TEXT | --body-file FILE) [--summary TEXT] [--kind note|research_packet|reporting_context_packet|draft_note|editor_note] [--reference LINEAGE] [--version N] [--author-label NAME] [--dry-run]",
     "both", _DRY, ""),
  _e("stories agent-note", "Add an AI agent's note to a Story, shown labelled as AI.",
     "--story LINEAGE --agent NAME (--body TEXT | --body-file FILE) [--summary TEXT] [--reference LINEAGE] [--version N] [--dry-run]", "both", _DRY, ""),
  _e("stories assign-research", "Open a research assignment for an idea Story.",
     "--story LINEAGE (--direction TEXT | --direction-file FILE) [--type research.multi] [--title TEXT] [--actor-label NAME] [--dry-run]", "operator", _DRY, ""),
  _e("stories draft", "Draft a Story's body with the writing model.", "--story LINEAGE [--direction TEXT] [--dry-run]", "operator", _DRY, ""),
  _e("stories outline", "Outline a Story with the writing model.", "--story LINEAGE [--direction TEXT] [--dry-run]", "operator", _DRY, ""),
  _e("stories fire-triggers", "Deliver the stage-entry triggers for the Story's current stage and version.", "--story LINEAGE", "operator", "writes", ""),
  _e("stories checklist-backfill", "Add the procedure checklist to Stories that lack one.", "[--dry-run] [--stage STAGE ...] [--page-size N]", "operator", _DRY, ""),
  _e("stories repair-versions", "Repair a Story's version records.", "--story LINEAGE [--dry-run]", "operator", _DRY, ""),
  _e("stories head-index", "Fill in and check the head stage key (one row per Story in the head stage index). A dry run unless --apply.",
     "[--apply] [--dry-run] [--stage STAGE ...] [--rate N]  (a dry run unless --apply; --rate is writes a second, default 5)", "both", "apply", ""),
  _e("stories repair-image-paths", "Repair image paths in a Story's versions. Read only unless you pass --write.", "--story LINEAGE [--write] [--bucket B] [--identity-pool-id ID]", "operator", "reads", ""),
  # ---- knowledge --------------------------------------------------------------------------------------------------
  _e("knowledge concepts search", "Find accepted concepts by meaning (name matches first, duplicates flagged). Free text needs OPENAI_API_KEY in this shell.",
     "\"free text\" [--limit N] [--json] | --list [--json]  (--list prints every accepted concept and needs no key)", "both", "reads", "find"),
  _e("knowledge concepts related", "List the concepts near a concept: confirmed links, aliases, co-occurrence. Needs no key.",
     "--concept NAME|#HASHTAG|NODEKEY [--limit N] [--json]", "both", "reads", "find"),
  _e("knowledge concepts import-types", "Operator: import the relation-type vocabulary. Writes immediately.", "[--config FILE]", "operator", "writes", ""),
  _e("knowledge concepts backfill", "Operator: backfill concept relations.", "[--config FILE] [--dry-run]", "operator", _DRY, ""),
  _e("knowledge entities list", "List concepts (about 100 generated ones by default). It cannot search: use `knowledge concepts search`.",
     "[--status accepted|generated|rejected|all] [--kind KIND] [--query TEXT] [--import-run ID] [--limit N] [--counts]  (--status defaults to generated: add --status accepted to see the concepts you can tag with)", "both", "reads", "find"),
  _e("knowledge entities link", "Link two concepts with a related_to link and the words that say how they relate.",
     "--key CONCEPT --to CONCEPT --note TEXT [--dry-run]  (CONCEPT is a node key, node id or lineage id; running it again replaces the words)", "editor", _DRY, "tag-and-link"),
  _e("knowledge entities accept", "Accept a generated concept.", "--key KEY --actor ai|human [--actor-name N] [--keep-links-unconfirmed] [--dry-run]", "operator", _DRY, ""),
  _e("knowledge entities reject", "Reject a generated concept.", "--key KEY --actor ai|human [--actor-name N] [--dry-run]", "operator", _DRY, ""),
  _e("knowledge entities rename", "Rename a concept.", "--key KEY --name NEW_NAME --actor ai|human [--actor-name N] [--dry-run]", "operator", _DRY, ""),
  _e("knowledge entities alias", "Add an alias to a concept.", "--key KEY --add NAME --actor ai|human [--actor-name N] [--dry-run]", "operator", _DRY, ""),
  _e("knowledge entities describe", "Set a concept's description.", "--key KEY --text DESCRIPTION --actor ai|human [--actor-name N] [--dry-run]", "operator", _DRY, ""),
  _e("knowledge entities accept-description", "A person accepts the description a concept already has.", "--key KEY --actor human [--actor-name N] [--dry-run]", "operator", _DRY, ""),
  _e("knowledge entities page", "Decide whether a concept has a public page.", "--key KEY --set yes|no|machine --actor ai|human [--actor-name N] [--dry-run]", "operator", _DRY, ""),
  _e("knowledge entities retype", "Change a concept's kind.", "--key KEY --kind KIND --actor ai|human [--actor-name N] [--dry-run]", "operator", _DRY, ""),
  _e("knowledge entities add", "Create an accepted concept (or find it), add its aliases, and tag Disambiguation when a name is ambiguous across kinds. Refuses a duplicate of an accepted concept.",
     "--kind KIND --name NAME [--alias A ...] --actor ai|human [--actor-name N] [--corpus-key K | --corpus-id ID] [--dry-run]  (repeat --alias for each other name)", "operator", _DRY, "tag-and-link"),
  _e("knowledge entities merge", "Merge a duplicate concept into the one that stays: its names become aliases, its mentions and relations move, it is superseded.",
     "--from KEY --into KEY --actor ai|human [--actor-name N] [--dry-run]  (afterwards: entities registry, snapshot, wiki sync --retire)", "operator", _DRY, "tag-and-link"),
  _e("knowledge entities duplicates", "List the pairs of accepted concepts in which one duplicates the other, with the rule and the merge command. Read only.",
     "[--kind KIND] [--json]", "operator", "reads", "tag-and-link"),
  _e("knowledge entities registry", "Write the entity registry JSON for `knowledge extract-entities --registry`.", "--out FILE [--vocabulary FILE]", "operator", "reads", ""),
  _e("knowledge clusters list", "List topic clusters.", "[--status proposed|accepted|rejected|all] [--limit N] --actor ai|human", "operator", "reads", ""),
  _e("knowledge relations list", "List typed relations between concepts.", "[--state proposed|accepted|rejected|all] [--limit N] --actor ai|human", "operator", "reads", ""),
  _e("knowledge query", "Query the shared knowledge engine: ranked records around a query text or anchors. Prints one JSON object; with no query it still succeeds, with an empty one.",
     "(--query TEXT | --anchor KIND:ID [--anchor ...] | --input FILE|-) [--profile researcher|reporter|reporting|editor|reviewer|chat] [--format structured|markdown|both] "
     "[--site HOST] [--max-tokens N] [--depth N] [--top-k N] [--include-kind KIND ...] [--exclude-kind KIND ...] [--execution auto|remote|local]",
     "both", "reads", "find"),
  # ---- ops content ------------------------------------------------------------------------------------------------
  _e("ops content publish", "Publish a saved version (the page goes live after the build; nothing purges the CDN).",
     "(--id LINEAGE-vN | --slug SLUG [--section KEY]) [--dry-run] [--verify [--verify-seconds N]] [--no-trigger] [--rebuild-app-id ID] [--rebuild-branch B] [--json]  "
     "(--id is the VERSION id, not the lineage id; exit 3 checklist open, 4 page not built, 5 still building, 6 cache not purged, 7 page stale)", "both", _DRY, "publish"),
  _e("ops content unpublish", "Take a published item off the site.", "(--id ITEM_ID | --slug SLUG [--section KEY]) [--dry-run] [--verify] [--no-trigger] [--json]", "both", _DRY, "publish"),
  _e("ops content update-live", "Re-project one Story, purge exactly its pages and the index pages that list it, check the live page.",
     "--story LINEAGE [--run] [--force-paths N] [--verify-seconds N] [--dry-run] [--json]  (without --run a wide purge stays a dry run)", "both", _DRY, "publish"),
  _e("ops content rerender", "Rebuild pages from the deployed hooks, then purge what was written (--no-invalidate: do not purge).",
     "(--story LINEAGE | --indexes | --all) [--no-invalidate] [--dry-run] [--json]", "both", _DRY, "publish"),
  _e("ops content refresh", "Purge exact pages at the edge now (both URL forms and the Markdown twin); never the whole site.",
     "(--path PATH [--path PATH ...] | --story LINEAGE | --indexes) [--run] [--force-paths N] [--dry-run] [--json]  (over 5 paths is a dry run until --run; over 25 refused without --force-paths N)",
     "both", _DRY, "publish"),
  _e("ops content inspect-page", "Read only unless --fix: the record, the stored page and what the edge serves, with one verdict.",
     "(--path PATH | --story LINEAGE) [--fix] [--run] [--force-paths N] [--json]", "both", "reads", "publish"),
  _e("ops content inspect", "Check GraphQL reachability and the AWS identity (operator lane).", "", "operator", "reads", ""),
  _e("ops content list", "List published articles.", "articles", "operator", "reads", ""),
  _e("ops content publish-gate", "Show or set the site's publish approval setting.", "show | set --approval required|not_required [--dry-run] [--json]", "operator", _DRY, ""),
  _e("ops content rebuild", "Trigger an Amplify rebuild of the reader or staging site.", "(--reader | --staging) [--app-id ID] [--branch B]", "operator", "writes", ""),
  # ---- ops relations / corpora -----------------------------------------------------------------------------------
  _e("ops relations import-types", "Import the relation-type vocabulary. Applies immediately: there is no --dry-run.", "[--config FILE]", "operator", "writes", ""),
  _e("ops relations backfill", "Backfill concept relations.", "[--config FILE] [--dry-run]", "operator", _DRY, ""),
  _e("knowledge concepts migrate-concept-tags", "Operator: move legacy related_to concept tags to tagged_with. Dry run by default.", "[--site KEY | --corpus-key KEY[,KEY]] [--limit N] [--apply] [--json]", "operator", "unknown", ""),
  _e("ops relations migrate-concept-tags", "Operator: move legacy related_to concept tags to tagged_with. Dry run by default.", "[--site KEY | --corpus-key KEY[,KEY]] [--limit N] [--apply] [--json]", "operator", "unknown", ""),
  _e("ops relations related", "Same as `papyrus knowledge concepts related`.", "--concept NAME|#HASHTAG|NODEKEY [--limit N] [--json]", "both", "reads", "find"),
  _e("ops relations search", "Same as `papyrus knowledge concepts search`.", "\"free text\" [--limit N] [--json] | --list", "both", "reads", "find"),
  _e("ops corpora status", "Show a corpus's local and cloud state.", "--corpus-key KEY [--config STEERING.yml] [--force] [--json]", "operator", "reads", ""),
  # ---- items ------------------------------------------------------------------------------------------------------
  _e("items link-references", "Operator backfill: link each Story to the References it used.", "--site KEY [--role consulted|cited|based_on] [--json] [--dry-run]", "operator", _DRY, ""),
  # ---- editorial --------------------------------------------------------------------------------------------------
  _e("editorial check-version", "Run the editorial rules on a saved version and store the result with it.", "--item LINEAGE-vN [--json]", "both", "writes", "checks"),
  _e("editorial check", "Check a draft file against the site's editorial policies (read only).", "--draft FILE [--section KEY] [--pack FILE] [--output FILE]", "both", "reads", ""),
  _e("editorial check-drafts", "Check every unpublished draft version not yet checked.", "[--limit N] [--dry-run]", "operator", _DRY, ""),
  _e("editorial suggest", "Rewrite options for one finding or a passage; never edits the draft.", "--draft FILE [--finding-id ID] [--select N] [--note TEXT]", "both", "reads", ""),
  # ---- sign-in ----------------------------------------------------------------------------------------------------
  _e("login", "Sign in with Google in a browser; prints nothing secret.", "SITE_HOST", "editor", "writes", "orientation"),
  _e("logout", "Remove the local session and attempt provider revocation.", "[SITE_HOST]", "editor", "writes", "orientation"),
  _e("whoami", "Renew and print every signed-in site's session as JSON (or one site's).", "[SITE_HOST]", "editor", "reads", "orientation"),
  _e("auth", "Inspect the selected session without opening a browser: `auth status`.", "status", "editor", "reads", "orientation"),
  _e("doctor", "Check the install, the sign-in and the site connection.", "[options]", "both", "reads", "orientation"),
  _e("links", "Print the console link of a Story (one version, or the drawer), Reference, Concept, Assignment or review item. Hand the editor these links.",
     "[--story LINEAGE|SLUG [--version N|VERSION_ID]] [--reference REFERENCE_ID|LINEAGE] [--concept NAME|NODEKEY] [--assignment ID] [--review ID] [--console-url URL] [--json]", "both", "reads", "write-story"),
  _e("guide", "Print the agent CLI guide, or one task's section of it.", "[TASK | --list]", "both", "reads", ""),
  # ---- guidelines (the operation table, src/papyrus_content/images/operations.py, is the source of the flags; a test keeps these in step) -------------
  _e("guidelines show", "Read a kind of guidelines (writing, image, video) for the site or one section: the stored document, its version, and the version id to pass to save.",
     "--kind KIND [--section KEY] [--version N] [--input-file PATH]", "editor", "reads", "guidelines"),
  _e("guidelines resolve", "Print the effective guidelines for the site, or a section laid over it, with where every field came from.",
     "--kind KIND [--section KEY] [--input-file PATH]", "editor", "reads", "guidelines"),
  _e("guidelines diff", "Show what saving a document would change, field by field and for binding rules; saves nothing.",
     "--kind KIND [--section KEY] --file PATH [--input-file PATH]", "editor", "reads", "guidelines"),
  _e("guidelines save", "Save a document as the next version of its kind and scope. Admins only; a binding-rule change needs a person.",
     "--kind KIND [--section KEY] --file PATH --reason TEXT --expected-current-version-id ID|none [--input-file PATH] [--dry-run]  "
     "(--dry-run prints the diff and saves nothing; an agent that changes a binding rule is refused with human_required)", "editor", _DRY, "guidelines"),
  _e("guidelines history", "List the versions of a kind of guidelines, newest first, with who changed it and why.",
     "--kind KIND [--section KEY] [--input-file PATH]", "editor", "reads", "guidelines"),
  # ---- figures (render reads the site's design system and writes local files only) -------------------------------------
  _e("figures render", "Check a figure and render its light and dark pictures (always both) with the site's design system. Needs Playwright and Chromium or Chrome.",
     "FOLDER... [--design-system DIR | --neutral-default] [--out DIR] [--check-only] [--json]  "
     "(FOLDER holds figure.svg and figure.json; with neither flag it reads the design system the signed-in site stores, `design-system show`, and stops when there is none; "
     "--design-system DIR overrides it with a folder; --neutral-default is the unbranded default for a site with no design system: say so; "
     "writes SLUG.png, SLUG.dark.png and SLUG.figure.json next to the figure, or into --out for one figure; --check-only writes nothing; exits 1 when any figure has a problem)",
     "both", "local", "figures"),
  _e("figures directive", "Print the ::image{} line for a figure's Story, from its figure.json.", "FOLDER", "both", "reads", "figures"),
  _e("figures rules", "Print the general figure rules every site follows (light and dark are both mandatory).", "", "both", "reads", "figures"),
  _e("figures primitives", "Print the shape library (glyphs, arrowhead, patterns) every figure can use.", "", "both", "reads", "figures"),
  # ---- design-system (the site's tokens, fonts, mapping and worked examples, kept in the backend) ----------------------
  _e("design-system show", "Show the design system the signed-in site stores: its version, roles, fonts, worked examples and figure settings (or that it has none).",
     "[--version N] [--json]", "both", "reads", "figures"),
  _e("design-system pull", "Write the stored design system into a folder, exactly as it was pushed (text verbatim, fonts as files, settings.json when set).",
     "DIR [--version N] [--force]  (DIR must be new or empty unless --force; the folder works as `figures render --design-system DIR`)", "both", "local", "figures"),
  _e("design-system push", "Publish a design system folder as the site's next design system version (a site repository does this at deploy). Checks it first; an unchanged folder makes no version.",
     "DIR --reason TEXT [--author-label NAME] [--dry-run]  (DIR holds mapping.json, its tokens file, the fonts it names, examples/NAME/figure.svg + figure.json, and an optional "
     "settings.json such as {\"requireDarkFigures\": true}; a folder with no settings.json keeps the site's settings; signed in the author is the person; "
     "--author-label is required on the operator lane)", "both", _DRY, "figures"),
])

_ENTRIES.update(dict([
  # ---- ideas (the full text is `ideas.commands.USAGE`) ------------------------------------------------------------
  _e("ideas digest", "Digest recent References by section and Cyclotron label (not by concept cluster or link); writes a local file.",
     "--publication KEY [--since 7d] [--status accepted[,pending]] [--max-references N] [--excerpts] [--out DIR] [--json]", "both", "local", "ideas"),
  _e("ideas synthesize", "Synthesize private story ideas from a digest and file them at the idea stage. Needs a model key (OPENAI_API_KEY).",
     "--publication KEY [--digest ID|PATH | --since 7d [--status ...] [--excerpts]] [--max 5] [--store items|json] [--feedback FILE] [--model NAME] [--dedupe-threshold X] "
     "[--max-cost-usd 0.50] [--story-days N] [--out DIR] [--report FILE] [--json]  (--store json keeps the ideas as local files only)", "both", "writes", "ideas"),
  _e("ideas trends", "File ideas from a weekly knowledge snapshot's trends. Needs a model key.",
     "--site KEY --snapshot PATH|URL [--store items|json] [--dry-run] [--max 3] [--trend-config FILE] [--model NAME] [--dedupe-threshold X] [--max-cost-usd 0.50] "
     "[--story-days N] [--exclude-host HOST ...] [--out DIR] [--report FILE] [--json]", "both", _DRY, "ideas"),
  _e("ideas monitor-stories", "File a cited story idea for accepted, monitored References that have none. Needs a model key.",
     "--site KEY [--corpus-key KEY] [--limit 3] [--since 7d] [--status accepted[,pending]] [--store items|json] [--dry-run] [--model NAME] [--dedupe-threshold X] "
     "[--max-cost-usd 0.50] [--story-days N] [--exclude-host HOST ...] [--out DIR] [--report FILE] [--json] [--packs-only | --single-only]", "both", _DRY, "ideas"),
  _e("ideas migrate-proposals", "Move open story_draft Proposals to Items at the idea stage; a dry run unless --write (needs an editor session).",
     "[--write] [--json]", "editor", "reads", ""),
  _e("ideas labels", "Editors' accept and decline decisions on generated ideas as JSON Lines for a Cyclotron (read only).", "[--out FILE]", "both", "reads", ""),
  _e("ideas select", "Select Stories for a feed or page by the site's signals.", "[options]  (see `docs/idea-pipeline.md`)", "unverified", "unknown", ""),
  # ---- ops content: the rest (the text is in `papyrus_content.cli.print_usage`) ---------------------------------------
  _e("ops content project", "Project the site's pages from the content store (all pages, listings, item pages, one item, or reconcile).",
     "(--all | --listings | --item-pages | --reconcile [--dry-run] [--only SITE_RELATIVE_PREFIX] [--amplify-outputs PATH] | --item ITEM_ID [--unpublished] | --unpublished-items FILE) "
     "[--from-dir CONTENT_DIR] [--out DIR] [--static-dir DIR] [--knowledge-dir DIR] [--allow-deletions] [--bucket B] [--json]  (--dry-run exists only with --reconcile)",
     "operator", "writes", "publish"),
  _e("ops content renditions", "Create image renditions (sizes) for stored pictures. Signed in with no --function-name it needs no AWS login.",
     "(--backfill | --source SRC_PATH) [--dry-run] [--media-bucket B] [--function-name F] [--workers N] [--json]", "both", _DRY, ""),
  _e("ops content export-published", "Export published items as Markus files.", "--out DIR [--tenant ID] [--drafts] [--clean] [--allow-empty] [--bucket B] [--auth guest] [--json]", "operator", "local", ""),
  _e("ops content upload-preview", "Upload a built preview folder to the preview bucket.", "--dir DIR [--bucket B] [--prefix preview/] [--json]", "operator", "writes", ""),
  _e("ops content markus-derive", "Derive the Markus intermediate form of a Markdown file.", "(--file article.md | --stdin) [--emit-ir]", "both", "reads", ""),
  _e("ops content import-markus", "Import Markus files as items.",
     "--content-dir DIR [--article-dirs a,b] [--draft-dirs drafts=articles] [--aliases-file F] [--image-source-dir D] [--bucket B] [--tenant ID] [--no-publish] [--force] [--dry-run] [--rebuild-app-id ID] [--json]",
     "operator", _DRY, ""),
  _e("ops content convert-bodies", "Convert stored bodies to the current format.", "[--models Item,PublishedItem] [--dry-run | --apply] [--json]  (a dry run unless --apply)", "operator", "unknown", ""),
  _e("ops content adopt-tenant-data", "Adopt pre-tenant rows into a tenant; a dry run unless --apply.", "--tenant ID [--apply] [--json]", "operator", "unknown", ""),
  _e("ops content schema-check", "Check that a GraphQL type has the named fields.", "[--type NAME] [--fields a,b]", "operator", "reads", ""),
]))

# ---- drafted entries -----------------------------------------------------------------------------------------------

_READS = {"reads", "dry-run", "writes", "unknown", "local"}


def _drafted(path: str) -> Usage | None:
  found = GENERATED.get(path)
  if found is None:
    return None
  usage, writes = found
  words = ["papyrus", *path.split()]
  text = usage or ""
  if text.lower().startswith("papyrus "):
    tokens = text.split()
    index = 0
    while index < len(tokens) and index < len(words) and tokens[index] == words[index]:
      index += 1
    text = " ".join(tokens[index:])
  if not usage:
    text = "[options]  (this command's flags are not documented yet: read its section of docs/operator-cli.md or the command's source)"
  return Usage(path, "", text, "unverified", writes if writes in _READS else "unknown")


GROUP_ORDER = {
  "references": ["search", "list", "show", "text", "make-catalog", "create-from-catalog", "link-concept", "link", "set-stars", "check-links", "approve", "reject", "suggest-links"],
  "stories": ["list", "show", "create", "save-version", "move", "set-slug", "set-stars", "link-concept", "link-story", "link-reference", "suggest-links",
              "check-links", "lens-check", "next", "step", "versions", "note", "agent-note"],
  "knowledge": ["concepts", "entities", "query"],
  "knowledge concepts": ["search", "related"],
  "knowledge entities": ["list", "link"],
  "ops": ["content", "relations", "corpora"],
  "ops content": ["publish", "update-live", "rerender", "refresh", "inspect-page", "unpublish"],
}


GROUP_SUMMARIES = {
  "knowledge concepts": "Find concepts by meaning and see the concepts near one (search, related); operator imports.",
  "knowledge entities": "List, link and review concepts (generated entities).",
  "knowledge clusters": "Review topic clusters (operator).",
  "knowledge relations": "Review typed relations between concepts (operator).",
  "knowledge topics": "Category and topic steering (operator).",
  "knowledge ontology": "Ontology maintenance (operator).",
  "knowledge wiki": "Public wiki pages: sync and publish (operator).",
  "knowledge run": "Undo or restore a knowledge run (operator).",
  "knowledge corpus": "Export the published items of a site as a Biblicus-ready folder.",
  "ops content": "Publish, re-render and refresh pages, and content maintenance.",
  "ops relations": "The relation-type vocabulary (operator).",
  "ops corpora": "Corpus status and sync (operator).",
  "ops categories": "Category steering (operator).",
  "ops messages": "Message maintenance (operator).",
  "ops site": "Site copy (operator).",
  "ops": "Content, relations, corpora, categories, messages and site operations.",
}
GROUP_SUMMARIES["guidelines"] = "Writing, image and video guidelines for the site or a section: read, resolve, diff, save and history."
GROUP_SUMMARIES["design-system"] = "The site's design system for figures (tokens, fonts, mapping, worked examples, figure settings), kept in the backend: show, pull, push."
GROUP_SUMMARIES["figures"] = "Diagrams, charts and illustrations: render a figure to a light and a dark picture and check it."


def _legacy(path: list[str]) -> Usage | None:
  from .group_commands import COMMAND_USAGE

  if len(path) < 2:
    return None
  text = COMMAND_USAGE.get((path[-2], path[-1]))
  if path[:2] == ["knowledge", "concepts"] and len(path) == 3:
    text = text or COMMAND_USAGE.get(("relations", path[2]))
  if not text:
    return None
  return Usage(" ".join(path), "", text, "unverified", "unknown")


def usage_for_path(path: list[str]) -> Usage | None:
  """The usage entry of the command named by `path` (`["knowledge", "concepts", "search"]`), or None for a group or an unknown word."""
  key = " ".join(path)
  if key in _ENTRIES:
    return _ENTRIES[key]
  legacy = _legacy(path)
  if legacy is not None:
    return legacy
  if path[:2] == ["knowledge", "concepts"] and len(path) == 3:
    alias = _ENTRIES.get(f"ops relations {path[2]}")
    if alias is not None:
      return Usage(key, alias.summary, alias.usage, alias.lane, alias.writes, alias.guide)
  return _drafted(key)


def summary_for_path(path: list[str]) -> str:
  if " ".join(path) in GROUP_SUMMARIES:
    return GROUP_SUMMARIES[" ".join(path)]
  if path and path[0] == "images":
    from papyrus_content.images.cli import COMMANDS

    for found in COMMANDS:
      if found["words"] == path[1:]:
        return found["summary"]
    return ""
  entry = usage_for_path(path)
  return entry.one_line() if entry is not None and entry.summary else ""


def has_documented_usage(path: list[str]) -> bool:
  entry = usage_for_path(path)
  return entry is not None and not entry.usage.startswith("[options]  (this command's flags are not documented yet")
