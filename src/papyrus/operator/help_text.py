from __future__ import annotations

import argparse

VERSION = "0.1.0"

TOP_LEVEL_HELP = """\
Usage: papyrus [--help] [--version] [--backend local|cloud] <group> <command> [options]

Operator groups:
  references    List or show references (local pod or cloud GraphQL)
  monitors      Due Hacker News collection and local worker checkpoints
  assignments   List newsroom assignments (cloud) or pod stories (local)
  knowledge     Knowledge query and steering utilities
  reporting     Reporting assignment workflow
  research      Research assignment workflow
  sections      Newsroom section maintenance
  editions      Edition planning
  procedures    Tactus and policy commands
  analysis      Analysis and reindex tooling
  ops           Content, corpora, categories, and messages
  videos        Video pipeline commands
  reader        Reader steering exports (reader feedback export)
  editorial     Editorial context and quality loop commands
  publication   Create the backend's canonical publication (publication init)
  site          Site repository operations (site google-secrets set|check)
  batch         Batch registration and enrichment
  login         Google newsroom sign-in using a configured native OAuth client
  logout        Remove the local user session and attempt provider revocation
  whoami        Renew and identify the selected newsroom user
  auth status   Inspect the selected user session without opening a browser

Backend selection:
  Use --backend local|cloud, PAPYRUS_BACKEND, or .papyrus/operator-cli.config.yaml.
  When unset, cloud is selected when GraphQL env is present; otherwise local pod path.
"""


def build_references_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(prog="papyrus references", add_help=False)
  subparsers = parser.add_subparsers(dest="command")

  list_parser = subparsers.add_parser("list", help="List references for the active backend")
  list_parser.add_argument("--limit", type=int, default=25)
  list_parser.add_argument("--status", default="")
  list_parser.add_argument("--order", default="newest")
  list_parser.add_argument("--corpus-key", default="")
  list_parser.add_argument("--backend", choices=["local", "cloud"], default="")

  show_parser = subparsers.add_parser("show", help="Show one reference")
  show_parser.add_argument("reference_id")
  show_parser.add_argument("--backend", choices=["local", "cloud"], default="")

  register_parser = subparsers.add_parser("register", help="Register a local pod reference artifact")
  register_parser.add_argument("--url", required=False, default="")
  register_parser.add_argument("--title", required=False, default="")
  register_parser.add_argument("--status", default="pending")
  register_parser.add_argument("--why", default="")
  register_parser.add_argument("--story", default="", help="Kanbus story id (or use local.defaultStory in config)")
  register_parser.add_argument("--corpus-key", default="")
  register_parser.add_argument("--id", default="", help="Optional stable reference id")
  register_parser.add_argument("--backend", choices=["local", "cloud"], default="local")

  return parser


def build_assignments_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(prog="papyrus assignments", add_help=False)
  subparsers = parser.add_subparsers(dest="command")

  list_parser = subparsers.add_parser("list", help="List cloud Assignments or local pod stories")
  list_parser.add_argument("--limit", type=int, default=25)
  list_parser.add_argument("--status", default="")
  list_parser.add_argument("--type", default="")
  list_parser.add_argument("--backend", choices=["local", "cloud"], default="")

  return parser


def build_knowledge_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(prog="papyrus knowledge", add_help=False)
  subparsers = parser.add_subparsers(dest="command")
  subparsers.add_parser("query", help="Run knowledge query")
  subparsers.add_parser("vector-index", help="Vector index maintenance")
  subparsers.add_parser("signals", help="Signal reports")
  ontology = subparsers.add_parser("ontology", help="Ontology utilities")
  ontology.add_argument("ontology_command")
  topics = subparsers.add_parser("topics", help="Category/topic steering")
  topics.add_argument("topics_command")
  concepts = subparsers.add_parser("concepts", help="Semantic relation concepts")
  concepts.add_argument("concepts_command")
  corpus = subparsers.add_parser("corpus", help="Export the published items of a site as a Biblicus-ready folder: export --out DIR")
  corpus.add_argument("corpus_command")
  subparsers.add_parser("publish-run", help="Import a workstation run (clusters, entities, front-matter entities); dry run unless --apply")
  subparsers.add_parser("snapshot", help="Write the public knowledge JSON (_data/knowledge/) for a site")
  entities = subparsers.add_parser("entities", help="Review entities (--actor ai|human required): list, accept, reject, rename, describe")
  entities.add_argument("entities_command")
  clusters = subparsers.add_parser("clusters", help="Review topic clusters (--actor ai|human required): list, accept, name, reject")
  clusters.add_argument("clusters_command")
  relations = subparsers.add_parser("relations", help="Review typed relations between entities (--actor ai|human required): list, accept, reject")
  relations.add_argument("relations_command")
  wiki = subparsers.add_parser("wiki", help="Public wiki pages: sync accepted entities and topics into drafts, publish with a review stamp")
  wiki.add_argument("wiki_command")
  return parser


def build_editorial_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(prog="papyrus editorial", add_help=False)
  subparsers = parser.add_subparsers(dest="command")
  context = subparsers.add_parser("context", help="Resolve current editorial guidance with source provenance")
  context.add_argument("--section")
  context.add_argument("--story")
  context.add_argument("--assignment")
  context.add_argument("--format", choices=["json", "text"], default="json")
  context.add_argument("--max-characters", type=int, default=0)
  check = subparsers.add_parser("check", help="Check a draft against the site's editorial policies (Humanus)")
  check.add_argument("--draft", required=True, help="Markus/Markdown body to check (read-only).")
  check.add_argument("--section", help="Desk key, for desk policies.")
  check.add_argument("--pack", help="Use this Humanus policy-pack file instead of the site's policies.")
  check.add_argument("--output")
  suggest = subparsers.add_parser("suggest", help="Rewrite options for one finding or a passage; never edits the draft")
  suggest.add_argument("--draft", required=True)
  suggest.add_argument("--finding-id")
  suggest.add_argument("--select")
  suggest.add_argument("--note")
  subparsers.add_parser("pack", help="Print the site's effective policy pack for a desk")
  subparsers.add_parser("import", help="Add a style profile's controls as editorial policies")
  subparsers.add_parser("policies", help="List policies, import a starter pack, or ensure the default packs")
  version = subparsers.add_parser("check-version", help="Check one saved version and store the result with it")
  version.add_argument("--item", required=True)
  drafts = subparsers.add_parser("check-drafts", help="Check every unpublished draft version not yet checked")
  drafts.add_argument("--limit", type=int)
  drafts.add_argument("--dry-run", action="store_true")
  return parser


def print_group_help(group: str) -> None:
  builders = {
    "references": build_references_parser,
    "assignments": build_assignments_parser,
    "knowledge": build_knowledge_parser,
    "editorial": build_editorial_parser,
  }
  builder = builders.get(group)
  if builder is None:
    from papyrus.operator.group_commands import generic_group_help

    text = generic_group_help(group)
    print(text if text is not None else TOP_LEVEL_HELP)
    return
  parser = builder()
  if group == "assignments":
    print("Cloud rows are GraphQL Assignment work records (kind: newsroom-assignment).")
    print("Local rows are Kanbus pod stories (kind: pod-story).")
    print("Use kbs for board columns, transitions, and workflow state.")
  parser.print_help()
