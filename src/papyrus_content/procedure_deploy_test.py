from __future__ import annotations

import json

import pytest

from papyrus_content import newsroom_commands, procedure_deploy as deploy


class Backend:
    def __init__(self):
        self.records, self.writes = {}, 0

    def get_record(self, model, record_id):
        return self.records.get((model, record_id))

    def create_record(self, model, payload):
        self.writes += 1
        self.records[(model, payload["id"])] = dict(payload)

    def update_record(self, model, payload):
        self.writes += 1
        self.records[(model, payload["id"])].update(payload)

    def list_by_index(self, index, key, limit=100):
        return [r for (m, _), r in self.records.items() if m == "ProcedureVersion" and r["procedureId"] == key]


@pytest.fixture(autouse=True)
def corpus_key(monkeypatch):
    monkeypatch.setattr("papyrus_content.steering.default_corpus_key", lambda *a, **k: "example-corpus")
    from papyrus_content import model_attachments
    monkeypatch.setattr(model_attachments, "upload_attachment_body", lambda client, attachment, body: attachment)


def test_unknown_default_token_stops_the_deploy():
    with pytest.raises(KeyError):
        deploy.resolve_defaults({"model": "$defaultNothing"})


def test_every_core_plan_has_a_digest_version_and_no_skills():
    plans = deploy.core_plans()
    assert len(plans) == 16
    for plan in plans:
        assert plan["versionId"].endswith(plan["contentDigest"]) and plan["skills"] == [] and plan["origin"] == "core"


def test_metadata_changes_publish_a_new_version(monkeypatch):
    before = {p["procedureKey"]: p["versionId"] for p in deploy.core_plans()}
    real = deploy.procedure_metadata_for_kind
    monkeypatch.setattr(deploy, "procedure_metadata_for_kind",
                        lambda kind: {**real(kind), "title": "Renamed"} if kind == "newsroom.editor" else real(kind))
    after = {p["procedureKey"]: p["versionId"] for p in deploy.core_plans()}
    assert [k for k in before if before[k] != after[k]] == ["newsroom.editor"]


def test_the_command_dry_runs_checks_and_applies(monkeypatch, capsys):
    backend = Backend()
    monkeypatch.setattr(newsroom_commands, "create_authoring_client", lambda *a, **k: (backend, {}))

    newsroom_commands.newsroom_seed_required_procedures(["--dry-run", "--json"])
    planned = json.loads(capsys.readouterr().out)
    assert planned["action"] == "dry-run" and {p["status"] for p in planned["procedures"]} == {"new"} and backend.writes == 0

    with pytest.raises(deploy.ProcedureDriftError, match="is missing"):
        newsroom_commands.newsroom_seed_required_procedures(["--check"])
    assert backend.writes == 0

    newsroom_commands.newsroom_seed_required_procedures(["--json"])
    applied = json.loads(capsys.readouterr().out)
    assert applied["action"] == "apply" and {p["status"] for p in applied["procedures"]} == {"registered"}
    writes = backend.writes

    newsroom_commands.newsroom_seed_required_procedures(["--check", "--json"])
    assert {p["status"] for p in json.loads(capsys.readouterr().out)["procedures"]} == {"unchanged"}
    newsroom_commands.newsroom_seed_required_procedures(["--json"])
    assert {p["status"] for p in json.loads(capsys.readouterr().out)["procedures"]} == {"unchanged"} and backend.writes == writes


def test_check_and_dry_run_together_are_refused():
    with pytest.raises(ValueError, match="--check or --dry-run"):
        newsroom_commands.newsroom_seed_required_procedures(["--check", "--dry-run"])


def test_a_site_registry_that_is_not_there_stops_the_deploy(tmp_path):
    with pytest.raises(deploy.ProcedureDeployError, match="is not there"):
        deploy.plan_deploy(site_registry=tmp_path / deploy.SITE_REGISTRY_FILE, root=tmp_path)


def test_overrides_must_name_a_listed_core_kind(tmp_path):
    path = tmp_path / deploy.SITE_REGISTRY_FILE
    path.write_text(json.dumps({"version": 1, "procedures": {"example.one": "a.tac"}, "overrides": ["newsroom.editor"]}))
    with pytest.raises(deploy.ProcedureDeployError, match="does not list a file"):
        deploy.plan_deploy(site_registry=path, root=tmp_path)
    path.write_text(json.dumps({"version": 1, "procedures": {"example.one": "a.tac"}, "overrides": ["example.one"]}))
    (tmp_path / "a.tac").write_text("-- papyrus-procedure-kind: example.one\nProcedure {}\n")
    with pytest.raises(deploy.ProcedureDeployError, match="no core procedure has that kind"):
        deploy.plan_deploy(site_registry=path, root=tmp_path)
