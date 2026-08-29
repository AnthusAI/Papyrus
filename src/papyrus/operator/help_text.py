from __future__ import annotations

import argparse

VERSION = "0.1.0"

TOP_LEVEL_HELP = """\
Usage: papyrus [--help] [--version] [--backend local|cloud] <group> <command> [options]

Operator groups:
  references    List or show references (local pod or cloud GraphQL)
  assignments   List newsroom assignments (cloud) or pod stories (local)
  auth          Mint cloud authoring JWTs
  knowledge     Knowledge query and steering utilities
  reporting     Reporting assignment workflow
  research      Research assignment workflow
  sections      Newsroom section maintenance
  editions      Edition planning
  procedures    Tactus and policy commands
  analysis      Analysis and reindex tooling
  ops           Content, corpora, categories, and messages
  videos        Video pipeline commands
  batch         Batch registration and enrichment

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


def build_auth_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(prog="papyrus auth", add_help=False)
  subparsers = parser.add_subparsers(dest="command")
  refresh = subparsers.add_parser("refresh", help="Mint PAPYRUS_GRAPHQL_JWT for cloud authoring")
  refresh.add_argument("--write-env", default="")
  refresh.add_argument("--ttl-seconds", default="")
  refresh.add_argument("--format", default="plain")
  subparsers.add_parser("refresh-jwt", help="Alias maintained for existing scripts")
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
  return parser


def print_group_help(group: str) -> None:
  builders = {
    "references": build_references_parser,
    "assignments": build_assignments_parser,
    "auth": build_auth_parser,
    "knowledge": build_knowledge_parser,
  }
  builder = builders.get(group)
  if builder is None:
    print(TOP_LEVEL_HELP)
    return
  parser = builder()
  if group == "assignments":
    print("Cloud rows are GraphQL Assignment work records (kind: newsroom-assignment).")
    print("Local rows are Kanbus pod stories (kind: pod-story).")
    print("Use kbs for board columns, transitions, and workflow state.")
  parser.print_help()
