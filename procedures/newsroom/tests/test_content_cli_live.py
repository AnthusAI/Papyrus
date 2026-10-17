"""Live content CLI checks (local file commands always; GraphQL when auth works)."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_content.env import load_dotenv

load_dotenv()

STEERING_CONFIG = REPO_ROOT / "corpora" / "papyrus-steering.yml"
ANALYSIS_PROFILES = REPO_ROOT / "corpora" / "papyrus-analysis-profiles.yml"

LOCAL_PYTHON_COMMANDS: list[tuple[list[str], str]] = [
    (["analysis", "profiles", "--profiles", str(ANALYSIS_PROFILES)], "Analysis profile summary"),
    (["analysis", "validate-profiles", "--profiles", str(ANALYSIS_PROFILES)], "Analysis profile validation"),
]

GRAPHQL_PYTHON_COMMANDS: list[tuple[list[str], str]] = [
    (["content", "inspect"], "GraphQL auth and reachability"),
    (["content", "schema-check", "--type", "Assignment"], "Assignment schema introspection"),
    (["content", "list", "articles"], "Published article listing"),
    (
        ["corpora", "status", "--config", str(STEERING_CONFIG), "--corpus-key", "AI-ML-research", "--json"],
        "Corpus worker readiness",
    ),
    (["assignments", "list", "--status", "open"], "Open assignment queue listing"),
    (
        [
            "references",
            "process-status",
            "--config",
            str(STEERING_CONFIG),
            "--corpus-key",
            "AI-ML-research",
            "--status",
            "accepted",
            "--json",
        ],
        "Accepted reference source readiness",
    ),
    (["assignments", "orphan-research-packets", "--json"], "Orphan research packet scan"),
    (
        ["analysis", "reindex-plan", "--profile", "canonical-topic-classifier", "--corpus-key", "AI-ML-research"],
        "Analysis reindex dry plan",
    ),
]

NODE_FALLBACK_COMMANDS: list[tuple[list[str], str]] = []


def _run_papyrus_content(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["poetry", "run", "papyrus", *argv],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        check=False,
    )


@lru_cache(maxsize=1)
def graphql_live_available() -> bool:
    if not os.environ.get("PAPYRUS_GRAPHQL_ENDPOINT", "").strip():
        return False
    result = _run_papyrus_content(["content", "inspect"])
    return result.returncode == 0


class ContentCliLocalLiveTests(unittest.TestCase):
    def test_local_python_commands(self) -> None:
        for command_argv, label in LOCAL_PYTHON_COMMANDS:
            with self.subTest(label=label, command=" ".join(command_argv)):
                result = _run_papyrus_content(command_argv)
                if result.returncode != 0:
                    self.fail(
                        f"{label} failed ({' '.join(command_argv)}):\n"
                        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
                    )


@unittest.skipUnless(
    os.environ.get("PAPYRUS_GRAPHQL_ENDPOINT", "").strip(),
    "Set PAPYRUS_GRAPHQL_ENDPOINT and AWS_PROFILE (papyrus-authoring role) for GraphQL live CLI tests.",
)
@unittest.skipUnless(
    graphql_live_available(),
    "GraphQL authoring auth is unavailable (no AWS credentials, wrong endpoint, or access denied). "
    "Set AWS_PROFILE to a profile that assumes the papyrus-authoring role and align PAPYRUS_GRAPHQL_ENDPOINT with that deployment.",
)
class ContentCliGraphQLLiveTests(unittest.TestCase):
    def test_python_graphql_commands(self) -> None:
        for command_argv, label in GRAPHQL_PYTHON_COMMANDS:
            with self.subTest(label=label, command=" ".join(command_argv)):
                result = _run_papyrus_content(command_argv)
                if result.returncode != 0:
                    self.fail(
                        f"{label} failed ({' '.join(command_argv)}):\n"
                        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
                    )

    def test_node_fallback_commands(self) -> None:
        if not NODE_FALLBACK_COMMANDS:
            self.skipTest("No Node fallback commands are configured for this branch.")
        for command_argv, label in NODE_FALLBACK_COMMANDS:
            with self.subTest(label=label, command=" ".join(command_argv)):
                result = _run_papyrus_content(command_argv)
                if result.returncode != 0:
                    self.fail(
                        f"{label} failed ({' '.join(command_argv)}):\n"
                        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
                    )


if __name__ == "__main__":
    unittest.main()
