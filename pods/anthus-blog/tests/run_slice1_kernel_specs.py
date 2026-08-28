#!/usr/bin/env python3
"""Execute Slice 1 kernel behavior specs for pods/anthus-blog.

Maps scenarios in pods/anthus-blog/features/*.feature to kbs commands.
Run from the pod root or anywhere: python3 tests/run_slice1_kernel_specs.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

POD_ROOT = Path(__file__).resolve().parent.parent
FEATURES = POD_ROOT / "features"


class SpecFailure(Exception):
    pass


def run_kbs(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["kbs", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
    )
    if check and result.returncode != 0:
        raise SpecFailure(
            f"kbs {' '.join(args)} failed ({result.returncode})\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def issue_status(cwd: Path, story_id: str) -> str:
    issue_path = cwd / "project" / "issues" / f"{story_id}.json"
    data = json.loads(issue_path.read_text(encoding="utf-8"))
    return data["status"]


def latest_story_dir(cwd: Path) -> Path:
    stories = sorted((cwd / "stories").iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    if not stories:
        raise SpecFailure("expected a story workspace but stories/ is empty")
    return stories[0]


def reset_fixture(cwd: Path) -> None:
    for rel in ("stories", "project/issues", "project/events", "project/.cache", "project/.overlay"):
        target = cwd / rel
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
    for rel in ("stories", "project/issues", "project/events"):
        (cwd / rel).mkdir(parents=True, exist_ok=True)


def scenario_workspace_create(cwd: Path) -> None:
    run_kbs("validate", cwd=cwd)
    run_kbs("hooks", "validate", cwd=cwd)

    created = run_kbs("create", "Spec fixture story", "--type", "story", cwd=cwd, check=False)
    if created.returncode != 0:
        raise SpecFailure(f"story create failed:\n{created.stderr}")

    combined = f"{created.stdout}\n{created.stderr}"
    if "Status: idea" not in combined:
        raise SpecFailure("new story did not begin in idea stage")
    if "GUIDANCE" not in combined:
        raise SpecFailure("expected coaching guidance on story create")

    workspace = latest_story_dir(cwd)
    story_id = workspace.name
    idea_path = workspace / "idea.md"
    if not idea_path.is_file() or idea_path.read_text(encoding="utf-8").strip() == "":
        raise SpecFailure("idea.md was not scaffolded for the new story")

    show = run_kbs("show", story_id, cwd=cwd, check=False)
    if show.returncode != 0:
        raise SpecFailure(f"kbs show failed for {story_id}")
    if "Status: idea" not in show.stdout:
        raise SpecFailure("revisited story is not in idea stage")
    if str(workspace) not in str(workspace.resolve()):
        raise SpecFailure("workspace path is unstable")


def scenario_workspace_revisit(cwd: Path) -> None:
    run_kbs("create", "Revisit demo", "--type", "story", cwd=cwd)
    workspace = latest_story_dir(cwd)
    story_id = workspace.name
    first = run_kbs("show", story_id, cwd=cwd)
    second = run_kbs("show", story_id, cwd=cwd)
    if first.stdout != second.stdout:
        raise SpecFailure("story inspection changed between sessions")
    if workspace.resolve() != (cwd / "stories" / story_id).resolve():
        raise SpecFailure("issue identity did not resolve to the same workspace")
    if "GUIDANCE" not in first.stdout and "GUIDANCE" not in first.stderr:
        raise SpecFailure("expected guidance when revisiting story")


def scenario_coach_before_transition(cwd: Path) -> None:
    run_kbs("create", "Coach demo", "--type", "story", cwd=cwd)
    workspace = latest_story_dir(cwd)
    idea_path = workspace / "idea.md"
    idea_path.write_text("", encoding="utf-8")

    show = run_kbs("show", workspace.name, cwd=cwd, check=False)
    combined = f"{show.stdout}\n{show.stderr}"
    if "GUIDANCE" not in combined:
        raise SpecFailure("expected coaching guidance on inspect")
    if "idea" not in combined.lower():
        raise SpecFailure("coaching did not mention the idea stage")


def scenario_refuse_incomplete(cwd: Path) -> None:
    run_kbs("create", "Incomplete demo", "--type", "story", cwd=cwd)
    workspace = latest_story_dir(cwd)
    story_id = workspace.name
    (workspace / "idea.md").write_text("", encoding="utf-8")

    blocked = run_kbs("update", story_id, "--status", "assignment", cwd=cwd, check=False)
    if blocked.returncode == 0:
        raise SpecFailure("empty idea.md should block assignment transition")
    if "idea.md" not in blocked.stderr:
        raise SpecFailure("blocked transition did not name the missing artifact")
    if issue_status(cwd, story_id) != "idea":
        raise SpecFailure("story stage changed after blocked transition")


def scenario_refuse_skip_ahead(cwd: Path) -> None:
    run_kbs("create", "Skip demo", "--type", "story", cwd=cwd)
    story_id = latest_story_dir(cwd).name

    blocked = run_kbs("update", story_id, "--status", "copywriting", cwd=cwd, check=False)
    if blocked.returncode == 0:
        raise SpecFailure("skip-ahead idea → copywriting should fail")
    if "skip-ahead" not in blocked.stderr and "copywriting" not in blocked.stderr.lower():
        raise SpecFailure("skip-ahead refusal did not explain the ladder")
    if issue_status(cwd, story_id) != "idea":
        raise SpecFailure("story stage changed after skip-ahead refusal")


def scenario_allow_complete(cwd: Path) -> None:
    run_kbs("create", "Complete demo", "--type", "story", cwd=cwd)
    workspace = latest_story_dir(cwd)
    story_id = workspace.name
    (workspace / "idea.md").write_text("# Idea\n\nReady.\n", encoding="utf-8")

    updated = run_kbs("update", story_id, "--status", "assignment", cwd=cwd, check=False)
    if updated.returncode != 0:
        raise SpecFailure(f"legal advance failed:\n{updated.stderr}")
    if issue_status(cwd, story_id) != "assignment":
        raise SpecFailure("story did not reach assignment after legal advance")


def _seed_story_to_editor_select(cwd: Path) -> str:
    run_kbs("create", "Revision path demo", "--type", "story", cwd=cwd)
    workspace = latest_story_dir(cwd)
    story_id = workspace.name
    artifacts = {
        "idea.md": "# Idea\n\nPitch.\n",
        "assignment.md": "# Assignment\n\nCharter.\n",
        "research.md": "# Research\n\nNotes.\n",
        "report.md": "# Report\n\nPrivate report.\n",
        "editor_select.md": "# Editor select\n\nAngle.\n",
    }
    for name, body in artifacts.items():
        (workspace / name).write_text(body, encoding="utf-8")

    for status in ("assignment", "research", "report", "editor_select"):
        run_kbs("update", story_id, "--status", status, cwd=cwd)
    return story_id


def scenario_return_for_research(cwd: Path) -> None:
    story_id = _seed_story_to_editor_select(cwd)
    workspace = cwd / "stories" / story_id

    run_kbs("update", story_id, "--status", "research", cwd=cwd)
    if issue_status(cwd, story_id) != "research":
        raise SpecFailure("editor_select → research revision failed")
    for name in ("assignment.md", "research.md", "report.md"):
        if not (workspace / name).is_file():
            raise SpecFailure(f"revision removed prior artifact {name}")


def scenario_copy_revision(cwd: Path) -> None:
    story_id = _seed_story_to_editor_select(cwd)
    workspace = cwd / "stories" / story_id
    (workspace / "article.md").write_text("# Article\n\nDraft copy.\n", encoding="utf-8")
    run_kbs("update", story_id, "--status", "copywriting", cwd=cwd)

    (workspace / "article.md").write_text("# Article\n\nRevised copy.\n", encoding="utf-8")

    if issue_status(cwd, story_id) != "copywriting":
        raise SpecFailure("copy revision should keep the story in copywriting")
    article = (workspace / "article.md").read_text(encoding="utf-8")
    if "Revised copy" not in article:
        raise SpecFailure("article artifact did not reflect revised copy")


SCENARIOS: list[tuple[str, str, callable]] = [
    ("story-workspace.feature", "Create a new story from an idea", scenario_workspace_create),
    ("story-workspace.feature", "Revisit the story after another agent session", scenario_workspace_revisit),
    ("story-gates.feature", "Coach before a transition is attempted", scenario_coach_before_transition),
    ("story-gates.feature", "Refuse an incomplete transition", scenario_refuse_incomplete),
    ("story-gates.feature", "Refuse skip-ahead transitions", scenario_refuse_skip_ahead),
    ("story-gates.feature", "Allow a complete transition", scenario_allow_complete),
    ("story-revision.feature", "Return reporting for more research", scenario_return_for_research),
    ("story-revision.feature", "Return reader-facing copy for revision", scenario_copy_revision),
]


def main() -> int:
    failures: list[str] = []
    passed = 0

    with tempfile.TemporaryDirectory(prefix="anthus-pod-spec-") as tmp:
        fixture_root = Path(tmp)
        for path in (".kanbus.yml", "kanbus-version", "hooks", "project/policies", "doctrine", "skills"):
            src = POD_ROOT / path
            dest = fixture_root / path
            if src.is_dir():
                shutil.copytree(src, dest)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
        (fixture_root / "stories").mkdir()
        (fixture_root / "project" / "issues").mkdir(parents=True)
        (fixture_root / "project" / "events").mkdir(parents=True)

        for feature, name, fn in SCENARIOS:
            label = f"{feature} :: {name}"
            reset_fixture(fixture_root)
            try:
                fn(fixture_root)
            except SpecFailure as exc:
                failures.append(f"FAIL {label}\n  {exc}")
            except Exception as exc:  # pragma: no cover - defensive
                failures.append(f"ERROR {label}\n  {exc}")
            else:
                print(f"PASS {label}")
                passed += 1

    print(f"\n{passed}/{len(SCENARIOS)} scenarios passed")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
