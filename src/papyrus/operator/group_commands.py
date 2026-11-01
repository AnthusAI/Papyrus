"""The subcommands of each `papyrus <group>`, one place for dispatch and for `--help`."""
from __future__ import annotations

REPORTING_COMMANDS = {
  "create": "create-reporting",
  "run": "run-reporting",
  "apply": "apply-reporting-packet",
  "review": "review-reporting-packet",
  "copywriting": "run-copywriting",
  "copywriting-output": "copywriting-output",
}
RESEARCH_COMMANDS = {
  "create": "create-research",
  "run": "run-research",
  "run-tavily-deep": "run-tavily-deep-research",
  "poll-tavily-deep": "poll-tavily-deep-research",
  "multi": "research-multi",
  "apply": "apply-research-packet",
  "process": "process-research-now",
  "packets": "research-packets",
  "process-proposals": "process-proposals",
}
SECTIONS_COMMANDS = {
  "import": "import-sections",
  "import-doctrine": "import-doctrine",
  "doctrine": "set-doctrine",
  "update": "update-section",
  "recount-summary": "recount-summary",
  "repair-message-status": "repair-message-status",
  "backfill-feed-fields": "backfill-feed-fields",
  "backfill-operational-indexes": "backfill-operational-indexes",
  "prune-attachments": "prune-attachments",
  "purge-planning": "purge-planning",
}
PROCEDURES_COMMANDS = ("seed-required", "register", "execute-tactus", "policy")
OPS_GROUPS = ("content", "corpora", "categories", "relations", "messages")
CONTENT_GROUPS_BY_PAPYRUS_GROUP = {"stories": "stories", "editions": "editions", "batch": "batch", "videos": "videos", "analysis": "analysis", "messages": "messages", "reader": "reader", "proposals": "proposals", "ideas": "ideas", "items": "items", "home-page": "home-page"}

# Usage lines for commands whose flags are worth showing in group help.
COMMAND_USAGE = {
  ("procedures", "register"): "--file PATH.tac --key PROCEDURE_KEY [--root DIR] [--title TEXT] [--description TEXT] [--dry-run] [--json]",
  ("stories", "create"): "--title TEXT [--section KEY] [--stage idea|assignment|reporting] [--summary TEXT] [--brief TEXT] [--reference ID ...] [--with-assignment] [--dry-run]",
  ("items", "link-references"): "--site KEY [--role consulted|cited|based_on] [--json] [--dry-run]",
  ("stories", "move"): "--story LINEAGE --stage STAGE [--reason TEXT] [--author-label NAME] [--dry-run]",
  ("stories", "save-version"): "--story LINEAGE --body-file FILE --reason TEXT --author-label NAME [--stage STAGE | --advance]",
  ("messages", "list"): "--kind form_submission [--status open|handled|all] [--form ID] [--limit N] [--json]",
  ("messages", "handle"): "--message-id ID [--note TEXT] [--author-label NAME] [--dry-run]",
  ("home-page", "snapshot"): "[--site KEY] [--site-bucket B | --out DIR] [--static-dir DIR] [--auth user|iam] [--amplify-outputs FILE] [--dry-run] [--json]",
  ("reader", "feedback"): "export [--since ISO_TIME] [--out FILE]",
  ("proposals", "create"): "--kind KIND --title TEXT (--body TEXT | --body-file FILE) [--summary LINE] [--target TYPE:ID ...] [--signals N --source TEXT] [--json]",
  ("proposals", "list"): "[--state STATE] [--json]",
  ("proposals", "show"): "PROPOSAL_ID [--json]",
  ("proposals", "transition"): "PROPOSAL_ID --to STATE [--reason TEXT] [--result approved|declined] [--json]",
  ("proposals", "approve"): "PROPOSAL_ID [--reason TEXT] [--json]  (editor review to approved; editors only)",
  ("proposals", "decline"): "PROPOSAL_ID [--reason TEXT] [--json]  (editors only)",
  ("proposals", "override"): "PROPOSAL_ID --result approved|declined --reason TEXT [--json]  (against the community; the reason is public; editors only)",
  ("proposals", "pin"): "PROPOSAL_ID [--json]  (editors only)",
  ("proposals", "unpin"): "PROPOSAL_ID [--json]  (editors only)",
  ("proposals", "hold"): "PROPOSAL_ID [--json]  (a held proposal cannot move; editors only)",
  ("proposals", "release"): "PROPOSAL_ID [--json]  (editors only)",
  ("proposals", "exclude-votes"): "PROPOSAL_ID --rule new-accounts-24h [--json]  (editors only)",
  ("proposals", "undo-exclusion"): "PROPOSAL_ID --exclusion EXCLUSION_ID [--json]  (editors only)",
  ("proposals", "needs-a-look"): "[--json]  (vote spikes, new-account surges, community vs AI; editors only, never published)",
  ("proposals", "publish"): "[--json]  (runs the reader snapshot, which writes _data/proposals/)",
  ("ideas", "digest"): "--publication KEY [--since 7d] [--status accepted[,pending]] [--max-references N] [--excerpts] [--out DIR] [--json]",
  ("ideas", "synthesize"): "--publication KEY [--digest ID|PATH | --since 7d] [--max 5] [--store json|proposals] [--feedback FILE] [--report FILE] [--out DIR] [--json]",
  ("publication", "init"): "--key KEY --name NAME",
  ("site", "google-secrets"): "set|check [--site PATH] [--profile NAME] [--account ID] [--region R] [--app-id ID] [--branch NAME] [--client-id ID] [--secret-stdin]",
  ("reporting", "create"): "--title TEXT [--section KEY] [--corpus-key KEY] [--summary TEXT] [--brief TEXT] [--dry-run]",
  ("sections", "doctrine"): "set --kind mission|policy --file MD [--dry-run]",
  ("sections", "update"): "--id SECTION [--editorial-mission-file F] [--editorial-policy-file F] [--assignment-guidance-file F] [--kill-criteria-file F] [--enabled true|false] [--dry-run]",
  ("research", "multi"): "ASSIGNMENT [--dry-run] [--json]   (assignment created with: research create --type research.multi)",
  ("research", "create"): "--title TEXT [--section KEY] [--corpus-key KEY] [--summary TEXT] [--brief TEXT] [--dry-run]",
}


def group_subcommands(group: str) -> list[str] | None:
  """Subcommand names of a group that has no argparse parser, or None when the group is unknown."""
  if group == "reporting":
    return list(REPORTING_COMMANDS)
  if group == "research":
    return list(RESEARCH_COMMANDS)
  if group == "sections":
    return list(SECTIONS_COMMANDS)
  if group == "procedures":
    return list(PROCEDURES_COMMANDS)
  if group == "publication":
    return ["init"]
  if group == "site":
    return ["google-secrets"]
  if group == "ops":
    return list(OPS_GROUPS)
  if group in CONTENT_GROUPS_BY_PAPYRUS_GROUP:
    from papyrus_content.cli import PORTED_COMMANDS

    names = sorted(route.split(":", 1)[1] for route in PORTED_COMMANDS if route.split(":", 1)[0] == group)
    if group == "analysis":
      names = sorted({*names, "test"})
    return names
  return None


def generic_group_help(group: str) -> str | None:
  names = group_subcommands(group)
  if names is None:
    return None
  lines = [f"Usage: papyrus {group} <command> [options]", "", "Commands:"]
  for name in names:
    usage = COMMAND_USAGE.get((group, name))
    lines.append(f"  {name}" + (f"  {usage}" if usage else ""))
  if group not in {"site", "proposals", "ideas"}:
    lines.append("")
    lines.append("Mutating commands write by default; pass --dry-run to preview.")
  return "\n".join(lines)
