from types import SimpleNamespace

from papyrus_content import cli, project_commands
from papyrus_content.projection.engine import DeletionGuard, DeletionRefused


def build(monkeypatch, tmp_path, **options):
    monkeypatch.setattr(project_commands, "load_projector", lambda _environment: SimpleNamespace())
    return project_commands._context_for(object(), {"out": str(tmp_path), **options})


def test_the_context_carries_the_default_deletion_guard(monkeypatch, tmp_path):
    assert build(monkeypatch, tmp_path).deletion_guard == DeletionGuard()


def test_allow_deletions_turns_the_guard_off(monkeypatch, tmp_path):
    assert build(monkeypatch, tmp_path, **{"allow-deletions": True}).deletion_guard is None


def test_a_static_directory_is_checked_for_staleness(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(project_commands, "warn_if_checkout_is_behind", seen.append)
    project_commands._projection_environment({"static-dir": str(tmp_path)})
    project_commands._projection_environment({})
    assert seen == [str(tmp_path)]


def test_a_refused_deletion_is_an_operator_error_without_a_traceback(monkeypatch, capsys):
    refusal = DeletionRefused(["wiki/a.html"], ["item-1"], 5)

    def refuse(_context):
        raise refusal

    monkeypatch.setattr(project_commands, "create_authoring_client", lambda: (object(), {}))
    monkeypatch.setattr(project_commands, "_context_for", lambda _client, _options: SimpleNamespace(projector=SimpleNamespace()))
    monkeypatch.setattr(project_commands, "project_all", refuse)
    assert cli.main(["content", "project", "--all"]) == 2
    err = capsys.readouterr().err
    assert "Refusing to delete 1 of 5 stored pages" in err
    assert "Traceback" not in err
