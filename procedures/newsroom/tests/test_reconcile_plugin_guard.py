"""A reconcile never deletes the pages a plugin projects, and the CLI resolves the plugin list the way the deployed backend does."""

from __future__ import annotations

import dataclasses
import json
from types import SimpleNamespace

import pytest

from papyrus_content import cli, project_commands
from papyrus_content.projection.engine import PluginPagesRefused, ProjectionContext, reconcile
from papyrus_content.projection.plugins import PLUGIN_PAGE_PREFIXES, PLUGINS_ENV, plugin_names_from_outputs
from papyrus_content.projection.source import PublishedContentSource
from papyrus_content.projection.standard import newsletter_pages
from papyrus_content.projection.standard.projector import StandardMarkusProjector
from procedures.newsroom.tests.standard_frontend_support import FIXTURES, ProjectedSite, fixture_settings

PAGE_KEYS = [newsletter_pages.site_key(name) for name in newsletter_pages.PAGE_NAMES]


@pytest.fixture()
def enabled():
    site = ProjectedSite("sectioned", plugins=("newsletter",))
    yield site
    site.cleanup()


def context_with(site, *, plugins, disabled=frozenset()):
    """The same bucket, read by a projector that was given ``plugins`` (as a CLI run without PAPYRUS_PLUGINS is)."""
    projector = StandardMarkusProjector.from_static_directory(site.static, environ=site.environ, plugins=plugins)
    return ProjectionContext(
        source=PublishedContentSource(site.client), projector=projector, writer=site.writer, redirect_store=site.redirects, disabled_plugins=disabled
    )


def stored(site):
    return set(site.tree)


def test_the_prefix_table_matches_where_the_newsletter_pages_are_written():
    assert all(key.startswith(PLUGIN_PAGE_PREFIXES["newsletter"]) for key in PAGE_KEYS)


def test_a_reconcile_with_the_deployed_plugin_list_keeps_the_pages(enabled):
    report = reconcile(context_with(enabled, plugins=("newsletter",)))
    assert report.orphan_pages == [] and report.protected_pages == []
    assert set(PAGE_KEYS) <= stored(enabled)


def test_a_reconcile_without_the_plugin_list_refuses_and_writes_nothing(enabled):
    before = enabled.digests()
    with pytest.raises(PluginPagesRefused) as raised:
        reconcile(context_with(enabled, plugins=()))
    assert set(raised.value.keys) == set(PAGE_KEYS)
    assert all(key in str(raised.value) for key in PAGE_KEYS)
    assert enabled.digests() == before


def test_a_dry_run_without_the_plugin_list_does_not_call_the_pages_orphans(enabled):
    report = reconcile(context_with(enabled, plugins=()), dry_run=True)
    assert report.orphan_pages == []
    assert set(report.protected_pages) == set(PAGE_KEYS)
    assert not report.drift
    assert report.to_dict()["protectedPluginPages"] == sorted(PAGE_KEYS)


def test_a_plugin_known_to_be_disabled_has_its_pages_reconciled_away(enabled):
    report = reconcile(context_with(enabled, plugins=(), disabled=frozenset({"newsletter"})))
    assert set(report.orphan_pages) == set(PAGE_KEYS)
    assert not set(PAGE_KEYS) & stored(enabled)


def test_only_considers_the_orphans_under_the_prefix(enabled):
    for key in ("wiki/page/a/index.html", "wiki/page/b/index.html", "notes/c/index.html"):
        enabled.writer.put(key, b"<html></html>")
    everything = reconcile(context_with(enabled, plugins=("newsletter",)), dry_run=True)
    assert {"wiki/page/a/index.html", "notes/c/index.html"} <= set(everything.orphan_pages)
    narrowed = reconcile(context_with(enabled, plugins=("newsletter",)), dry_run=True, only="wiki/page/")
    assert narrowed.orphan_pages == ["wiki/page/a/index.html", "wiki/page/b/index.html"]
    reconcile(context_with(enabled, plugins=("newsletter",)), only="/wiki/page/")
    assert stored(enabled) >= {"notes/c/index.html"} | set(PAGE_KEYS)
    assert not {"wiki/page/a/index.html", "wiki/page/b/index.html"} & stored(enabled)


def test_only_does_not_trip_the_plugin_guard_outside_its_prefix(enabled):
    enabled.writer.put("wiki/page/a/index.html", b"<html></html>")
    report = reconcile(context_with(enabled, plugins=()), only="wiki/page/")
    assert report.orphan_pages == ["wiki/page/a/index.html"]
    assert set(PAGE_KEYS) <= stored(enabled)


def test_only_and_the_plugin_guard_honour_the_site_base_path():
    settings = fixture_settings("sectioned")
    settings["urls"] = {**settings.get("urls", {}), "basePath": "/posts"}
    settings.pop("images", None)
    settings.pop("media", None)
    site = ProjectedSite(settings=settings, content=FIXTURES / "sectioned" / "content", plugins=("newsletter",))
    try:
        keys = [f"posts/{key}" for key in PAGE_KEYS]
        assert set(keys) <= stored(site)
        site.writer.put("posts/wiki/page/a/index.html", b"<html></html>")
        site.writer.put("wiki/page/outside/index.html", b"<html></html>")
        with pytest.raises(PluginPagesRefused) as raised:
            reconcile(context_with(site, plugins=()))
        assert set(raised.value.keys) == set(keys)
        narrowed = reconcile(context_with(site, plugins=("newsletter",)), dry_run=True, only="wiki/page/")
        assert narrowed.orphan_pages == ["posts/wiki/page/a/index.html"]
    finally:
        site.cleanup()


# ------------------------------------------------------------------ the CLI resolves the plugin list


def write_outputs(tmp_path, plugins: dict | None):
    custom = {} if plugins is None else {"custom": {"papyrusPlugins": plugins}}
    path = tmp_path / "amplify_outputs.json"
    path.write_text(json.dumps({"version": "1.4", **custom}), encoding="utf-8")
    return str(path)


def test_the_deployed_list_is_the_keys_of_custom_papyrus_plugins(tmp_path):
    assert plugin_names_from_outputs(tmp_path / "missing.json") is None
    assert plugin_names_from_outputs(__import__("pathlib").Path(write_outputs(tmp_path, None))) == ()
    assert plugin_names_from_outputs(__import__("pathlib").Path(write_outputs(tmp_path, {"newsletter": {}, "signup": {}}))) == ("newsletter", "signup")


def test_the_cli_reads_the_plugin_list_from_the_site_config(monkeypatch, tmp_path):
    monkeypatch.delenv(PLUGINS_ENV, raising=False)
    outputs = write_outputs(tmp_path, {"newsletter": {}, "signup": {}})
    monkeypatch.chdir(tmp_path)
    environment = project_commands._projection_environment({"amplify-outputs": outputs})
    assert environment[PLUGINS_ENV] == "newsletter,signup"


def test_the_environment_override_wins_and_is_not_verified_against_a_different_deployment(monkeypatch, tmp_path):
    outputs = write_outputs(tmp_path, {"newsletter": {}})
    monkeypatch.setenv(PLUGINS_ENV, "signup")
    environment = project_commands._projection_environment({"amplify-outputs": outputs})
    assert environment[PLUGINS_ENV] == "signup"
    resolution = project_commands._resolve_plugins({"amplify-outputs": outputs}, {PLUGINS_ENV: "signup"})
    assert resolution.overridden and not resolution.verified and "differs from the deployed one" in resolution.problem()


def test_the_environment_override_that_matches_the_deployment_is_verified(tmp_path):
    outputs = write_outputs(tmp_path, {"newsletter": {}})
    assert project_commands._resolve_plugins({"amplify-outputs": outputs}, {PLUGINS_ENV: "newsletter"}).verified


def build(monkeypatch, tmp_path, outputs, **options):
    monkeypatch.setattr(project_commands, "load_projector", lambda _environment: SimpleNamespace())
    return project_commands._context_for(object(), {"out": str(tmp_path / "out"), "amplify-outputs": outputs, **options})


def test_a_context_marks_the_plugins_the_deployment_lacks_as_disabled(monkeypatch, tmp_path):
    monkeypatch.delenv(PLUGINS_ENV, raising=False)
    assert build(monkeypatch, tmp_path, write_outputs(tmp_path, {})).disabled_plugins == {"newsletter"}
    assert build(monkeypatch, tmp_path, write_outputs(tmp_path, {"newsletter": {}})).disabled_plugins == frozenset()
    assert build(monkeypatch, tmp_path, str(tmp_path / "missing.json")).disabled_plugins == frozenset()


def run_reconcile_cli(monkeypatch, capsys, tmp_path, *flags, env=None, outputs=None):
    monkeypatch.delenv(PLUGINS_ENV, raising=False)
    if env is not None:
        monkeypatch.setenv(PLUGINS_ENV, env)
    reached = []
    monkeypatch.setattr(project_commands, "create_authoring_client", lambda: reached.append("client") or (object(), {}))
    monkeypatch.setattr(project_commands, "_context_for", lambda _client, _options: SimpleNamespace(projector=SimpleNamespace()))
    monkeypatch.setattr(project_commands, "reconcile", lambda _context, **kwargs: reached.append(kwargs) or SimpleNamespace(
        dry_run=kwargs["dry_run"], drift=False, ok=True, errors=[], protected_pages=[], to_dict=lambda: {}, stale_items=[], removed_items=[],
        stale_listings=[], orphan_pages=[], redirects_repaired=0))
    outputs = outputs or write_outputs(tmp_path, {"newsletter": {}})
    code = cli.main(["content", "project", "--reconcile", "--amplify-outputs", outputs, *flags])
    return code, reached, capsys.readouterr()


def test_a_reconcile_refuses_when_the_deployed_plugin_list_is_unknown(monkeypatch, capsys, tmp_path):
    code, reached, output = run_reconcile_cli(monkeypatch, capsys, tmp_path, outputs=str(tmp_path / "missing.json"))
    assert code != 0 and reached == []
    assert "Refusing to reconcile" in output.err and "missing or unreadable" in output.err


def test_a_reconcile_refuses_when_the_override_differs_from_the_deployed_list(monkeypatch, capsys, tmp_path):
    code, reached, output = run_reconcile_cli(monkeypatch, capsys, tmp_path, env="")
    assert code != 0 and reached == []
    assert "differs from the deployed one" in output.err and "newsletter" in output.err


def test_a_reconcile_with_the_deployed_list_goes_ahead_and_passes_only_on(monkeypatch, capsys, tmp_path):
    code, reached, _ = run_reconcile_cli(monkeypatch, capsys, tmp_path, "--only", "wiki/page/")
    assert code == 0
    assert reached == ["client", {"dry_run": False, "only": "wiki/page/"}]
    code, reached, _ = run_reconcile_cli(monkeypatch, capsys, tmp_path, env="newsletter")
    assert code == 0 and reached[1]["only"] is None


def test_a_dry_run_is_not_refused_for_an_unknown_list(monkeypatch, capsys, tmp_path):
    code, reached, _ = run_reconcile_cli(monkeypatch, capsys, tmp_path, "--dry-run", outputs=str(tmp_path / "missing.json"))
    assert code == 0 and reached[1]["dry_run"] is True


def test_only_without_a_value_is_an_operator_error(monkeypatch, capsys, tmp_path):
    code, _, output = run_reconcile_cli(monkeypatch, capsys, tmp_path, "--only")
    assert code != 0 and "--only needs" in output.err
