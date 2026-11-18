"""``papyrus agents apply`` as the deploy runs it: the command's flags, its output and its exit codes (the rules are in agent-definitions-on-release.feature)."""
import io
import json
import shutil

import pytest
import yaml

from papyrus_content.agent_definitions import cli, definition
from papyrus_content.agent_definitions.release import registered_schedules


class Site:
    def __init__(self):
        self.rows, self.writes = {}, 0

    def list_tenant_rows(self, model, fields):
        return list(self.rows.values())

    def get_record(self, model, record_id):
        return self.rows.get(record_id)

    def create_record(self, model, payload):
        self.writes += 1
        self.rows[payload["id"]] = dict(payload)

    def update_record(self, model, payload):
        self.writes += 1
        self.rows[payload["id"]] = {**self.rows[payload["id"]], **payload}


@pytest.fixture
def core(tmp_path):
    folder = tmp_path / "core"
    shutil.copytree(definition.CORE_DIRECTORY, folder, ignore=shutil.ignore_patterns(".*"))
    return folder   # the shipped definitions as they are: the rating agent's procedure is in the registry


def run(argv, site, core, tmp_path):
    out = io.StringIO()
    code = cli.apply_command([*argv, "--core", str(core), "--root", str(tmp_path)], out, client_factory=lambda: site)
    return code, json.loads(out.getvalue())


def test_apply_writes_then_writes_nothing(core, tmp_path):
    site = Site()
    code, body = run([], site, core, tmp_path)
    assert code == 0 and body["result"]["action"] == "apply"
    assert [(item["definitionId"], item["status"], item["applied"]) for item in body["result"]["definitions"]] == [("rate", "new", True)]
    record = site.rows["rate"]
    assert record["enabled"] is False and record["definitionVersion"] == 1 and "responsibility" not in record
    written = site.writes
    code, body = run([], site, core, tmp_path)
    assert code == 0 and site.writes == written and body["result"]["definitions"][0]["status"] == "unchanged"


def test_dry_run_reads_and_writes_nothing(core, tmp_path):
    site = Site()
    code, body = run(["--dry-run"], site, core, tmp_path)
    assert code == 0 and body["result"]["action"] == "dry-run" and body["result"]["definitions"][0]["status"] == "new"
    assert site.writes == 0


def test_check_exits_2_on_drift_and_0_when_in_step(core, tmp_path):
    site = Site()
    code, body = run(["--check"], site, core, tmp_path)
    assert code == 2 and body["error"]["code"] == "constraint_conflict" and "rate is missing" in body["error"]["message"]
    run([], site, core, tmp_path)
    code, body = run(["--check"], site, core, tmp_path)
    assert code == 0 and body["result"]["action"] == "check" and site.writes == 2


def test_unknown_procedure_stops_before_any_write(core, tmp_path):
    data = yaml.safe_load((core / "rate.yaml").read_text(encoding="utf-8"))
    data["procedure"] = "nothing.registered"   # a procedure no registry lists
    (core / "rate.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    site = Site()
    code, body = run([], site, core, tmp_path)
    assert code == 2 and "rate: the procedure nothing.registered is not registered" in body["error"]["message"] and site.writes == 0


def test_the_shipped_rating_definition_names_a_registered_procedure(tmp_path):
    site = Site()
    code, body = run(["--dry-run"], site, definition.CORE_DIRECTORY, tmp_path)
    assert code == 0 and body["result"]["definitions"][0]["status"] == "new" and site.writes == 0


def test_a_site_folder_is_read_from_the_root_and_validated_first(core, tmp_path):
    folder = tmp_path / "papyrus-site-agents"
    folder.mkdir()
    (folder / "extra.yaml").write_text("id: extra\n", encoding="utf-8")
    site = Site()
    code, body = run([], site, core, tmp_path)
    assert code == 2 and "extra" in body["error"]["message"] and "Nothing was written" in body["error"]["message"] and site.writes == 0


def test_flags_are_checked(core, tmp_path):
    for argv in (["--dry-run", "--check"], ["--nope"], ["--dir", str(tmp_path / "missing")]):
        code, body = run(argv, Site(), core, tmp_path)
        assert code == 2 and body["ok"] is False


def test_registered_schedules_skip_retired_and_unscheduled():
    live = {"id": "a", "definition": json.dumps({"wakes": {"schedule": {"cron": "0 1 * * *", "timeZone": "UTC"}}})}
    retired = {**live, "id": "b", "definitionRetiredAt": "2026-11-17T00:00:00Z"}
    changes_only = {"id": "c", "definition": json.dumps({"wakes": {"changes": [{"kind": "Item", "change": "step_changed"}]}})}
    assert list(registered_schedules([live, retired, changes_only, {"id": "d"}])) == ["a"]


def test_an_automation_that_exists_without_a_tenant_id_stops_the_apply_and_names_the_backfill(core, tmp_path):
    site = Site()
    site.list_tenant_rows = lambda model, fields: []   # the tenantId index lists nothing: the row carries no tenantId
    site.rows["rate"] = {"id": "rate"}
    code, body = run([], site, core, tmp_path)
    assert code == 2 and "rate" in body["error"]["message"] and "carries no tenantId" in body["error"]["message"]
    assert "content backfill-tenant-id" in body["error"]["message"] and site.writes == 0


class StoreSite(Site):
    tenant_id = "alpha"


def listeners_run(argv, core, tmp_path, store):
    out = io.StringIO()
    code = cli.listeners_command([*argv, "--core", str(core), "--root", str(tmp_path)], out, client_factory=lambda: StoreSite(), site_store_factory=lambda client: store)
    return code, json.loads(out.getvalue())


def test_listeners_writes_the_index_once_and_check_fails_on_a_difference(core, tmp_path):
    from papyrus_content.site_store import SiteStore
    from papyrus_content.site_store_test import FakeS3, FakeTable

    store = SiteStore(FakeS3(), "bucket", FakeTable(), now=lambda: "2026-11-18T00:00:00Z")
    code, body = listeners_run(["--check"], core, tmp_path, store)
    assert code == 2 and body["error"]["code"] == "constraint_conflict" and store.current_version("alpha", "listeners") == 0
    code, body = listeners_run(["--dry-run"], core, tmp_path, store)
    assert code == 0 and body["result"]["action"] == "dry-run" and body["result"]["index"]["applied"] is False and store.current_version("alpha", "listeners") == 0
    code, body = listeners_run([], core, tmp_path, store)
    assert code == 0 and body["result"]["index"]["applied"] is True and store.current_version("alpha", "listeners") == 1
    code, body = listeners_run([], core, tmp_path, store)
    assert code == 0 and body["result"]["index"]["action"] == "unchanged" and store.current_version("alpha", "listeners") == 1
    assert listeners_run(["--check"], core, tmp_path, store)[0] == 0


def test_listeners_needs_the_site_tenant(core, tmp_path):
    out = io.StringIO()
    code = cli.listeners_command(["--core", str(core), "--root", str(tmp_path)], out, client_factory=lambda: Site(), site_store_factory=lambda client: None)
    assert code == 2 and "tenant" in json.loads(out.getvalue())["error"]["message"]
