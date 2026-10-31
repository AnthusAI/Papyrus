from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SITE_AFFECTING_PATH_PREFIXES = (
    "app/",
    "components/",
    "lib/",
    "renderers/",
    "amplify/",
    "packages/",
    "infra/amplify-app-shell/",
    "scripts/videoml/",
    "src/papyrus_content/",
)

SITE_AFFECTING_EXACT_PATHS = ("middleware.ts",)

PATH_FRAGMENTS_THAT_NEVER_SHIP = (".test.", "/fixtures/", "/seed/", "/tests/", "__pycache__")

RELEASE_NOTES_MARKER_PATTERN = re.compile(r"^Affects sites: (yes|no)\s*$", re.MULTILINE)


def path_affects_sites(path: str) -> bool:
    if any(fragment in path for fragment in PATH_FRAGMENTS_THAT_NEVER_SHIP):
        return False
    if path in SITE_AFFECTING_EXACT_PATHS:
        return True
    return path.startswith(SITE_AFFECTING_PATH_PREFIXES)


def release_affects_sites(changed_paths: list[str]) -> bool:
    return any(path_affects_sites(path) for path in changed_paths)


def release_notes_marker(affects_sites: bool) -> str:
    return f"Affects sites: {'yes' if affects_sites else 'no'}"


def affects_sites_from_release_notes(release_notes: str) -> bool:
    match = RELEASE_NOTES_MARKER_PATTERN.search(release_notes or "")
    return match is None or match.group(1) == "yes"


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.lstrip("v").split("."))


def plan_site_bump(current_version: str, releases: list[dict]) -> dict:
    newer_releases = sorted(
        (
            release
            for release in releases
            if not release.get("prerelease")
            and version_key(release["tagName"]) > version_key(current_version)
        ),
        key=lambda release: version_key(release["tagName"]),
    )
    site_affecting = [
        release["tagName"]
        for release in newer_releases
        if affects_sites_from_release_notes(release.get("body", ""))
    ]
    if not site_affecting:
        return {"bump_needed": False, "target": None, "site_affecting_releases": []}
    return {
        "bump_needed": True,
        "target": newer_releases[-1]["tagName"].lstrip("v"),
        "site_affecting_releases": site_affecting,
    }


def changed_paths_between(base_ref: str, head_ref: str) -> list[str]:
    completed = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}..{head_ref}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in completed.stdout.splitlines() if line]


def command_classify(arguments: argparse.Namespace) -> int:
    affects_sites = release_affects_sites(changed_paths_between(arguments.base, arguments.head))
    print(release_notes_marker(affects_sites))
    if arguments.github_output:
        with Path(arguments.github_output).open("a", encoding="utf-8") as output:
            output.write(f"affects_sites={'true' if affects_sites else 'false'}\n")
    return 0


def command_plan_bump(arguments: argparse.Namespace) -> int:
    releases = json.loads(Path(arguments.releases_json).read_text(encoding="utf-8"))
    print(json.dumps(plan_site_bump(arguments.current, releases), indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Classify Papyrus releases and plan weekly site bumps.")
    commands = parser.add_subparsers(dest="command", required=True)
    classify = commands.add_parser("classify")
    classify.add_argument("--base", required=True)
    classify.add_argument("--head", required=True)
    classify.add_argument("--github-output")
    classify.set_defaults(handler=command_classify)
    plan = commands.add_parser("plan-bump")
    plan.add_argument("--current", required=True)
    plan.add_argument("--releases-json", required=True)
    plan.set_defaults(handler=command_plan_bump)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    return arguments.handler(arguments)


if __name__ == "__main__":
    sys.exit(main())
