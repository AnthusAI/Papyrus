"""`stories save-version --images` and a figure with no dark picture: warn by default, refuse when the site (or the editor) asks. No AWS, no backend."""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from fake_client import FakeAuthoringClient  # noqa: E402

from papyrus_content import story_commands  # noqa: E402
from papyrus_content.story_images import is_figure_picture, plan_lines, plan_story_images  # noqa: E402

LINEAGE = "item-figure-story"
BODY = '::image{src="chart.png" alt="A chart" layout="inline"}\n'


def picture(path: Path, size=(40, 20)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (1, 2, 3)).save(path)
    return path


def make_figure(folder: Path, slug: str = "chart", dark: bool = True) -> None:
    picture(folder / f"{slug}.png")
    if dark:
        picture(folder / f"{slug}.dark.png")
    (folder / f"{slug}.figure.json").write_text(json.dumps({"slug": slug, "themes": ["light", "dark"]}))


def test_a_picture_with_a_figure_sidecar_is_a_figure(tmp_path):
    make_figure(tmp_path)
    picture(tmp_path / "photo.png")
    assert is_figure_picture(tmp_path / "chart.png")
    assert not is_figure_picture(tmp_path / "photo.png")


def test_a_figure_with_only_a_light_picture_is_listed_and_warned_about(tmp_path):
    make_figure(tmp_path, dark=False)
    plan = plan_story_images(BODY, tmp_path, slug="story")
    assert plan.light_only_figures == ["chart.png"]
    warning = [line for line in plan_lines(plan, "item-v2") if "figure-light-only" in line]
    assert len(warning) == 1 and "chart.png" in warning[0] and "papyrus figures render" in warning[0]


def test_a_figure_with_both_pictures_is_not_warned_about(tmp_path):
    make_figure(tmp_path)
    plan = plan_story_images(BODY, tmp_path, slug="story")
    assert plan.light_only_figures == []
    assert not any("figure-light-only" in line for line in plan_lines(plan, "item-v2"))


def test_a_photograph_with_no_dark_picture_is_not_a_figure_and_is_not_warned_about(tmp_path):
    picture(tmp_path / "chart.png")
    plan = plan_story_images(BODY, tmp_path, slug="story")
    assert plan.light_only_figures == []


def test_srcDark_none_on_a_figure_is_still_light_only(tmp_path):
    make_figure(tmp_path)
    plan = plan_story_images('::image{src="chart.png" srcDark="none" alt="A chart"}\n', tmp_path, slug="story")
    assert plan.light_only_figures == ["chart.png"]


def test_a_figure_used_twice_is_listed_once(tmp_path):
    make_figure(tmp_path, dark=False)
    plan = plan_story_images(BODY + "\n" + BODY, tmp_path, slug="story")
    assert plan.light_only_figures == ["chart.png"]


def fresh_client() -> FakeAuthoringClient:
    client = FakeAuthoringClient({
        "Item": [{"id": f"{LINEAGE}-v1", "lineageId": LINEAGE, "versionNumber": 1, "versionState": "current", "headline": "A story", "title": "A story", "stage": "idea", "slug": "a-story", "type": "untyped", "section": "news"}],
    })
    client.endpoint = "https://example.test/graphql"
    return client


def save_dry_run(tmp_path: Path, *flags: str, environment: dict | None = None):
    out, failure = io.StringIO(), None
    body = tmp_path / "body.md"
    body.write_text(BODY)
    with contextlib.redirect_stdout(out), \
            mock.patch.dict(os.environ, environment or {}), \
            mock.patch.object(story_commands, "create_authoring_client", return_value=(fresh_client(), {})), \
            mock.patch("papyrus_content.user_auth_mode.user_auth_requested", return_value=False):
        try:
            story_commands.stories_save_version(["--story", LINEAGE, "--body-file", str(body), "--reason", "r", "--author-label", "ops",
                                                 "--images", str(tmp_path / "pictures"), "--dry-run", *flags])
        except BaseException as error:  # noqa: BLE001
            failure = error
    return out.getvalue(), failure


def test_save_version_warns_and_still_saves_by_default(tmp_path):
    make_figure(tmp_path / "pictures", dark=False)
    out, failure = save_dry_run(tmp_path)
    assert failure is None
    assert "figure-light-only" in out and "dry run" in out


def test_save_version_refuses_with_the_flag(tmp_path):
    make_figure(tmp_path / "pictures", dark=False)
    out, failure = save_dry_run(tmp_path, "--require-dark-figures")
    assert isinstance(failure, ValueError) and "no dark picture" in str(failure) and "chart.png" in str(failure)
    assert out == ""


def test_save_version_refuses_when_the_environment_asks(tmp_path):
    make_figure(tmp_path / "pictures", dark=False)
    _out, failure = save_dry_run(tmp_path, environment={"PAPYRUS_REQUIRE_DARK_FIGURES": "1"})
    assert isinstance(failure, ValueError)


@pytest.mark.parametrize("flags", [("--require-dark-figures",), ()])
def test_a_complete_figure_saves_without_a_warning_even_when_dark_is_required(tmp_path, flags):
    make_figure(tmp_path / "pictures")
    out, failure = save_dry_run(tmp_path, *flags)
    assert failure is None
    assert "figure-light-only" not in out
