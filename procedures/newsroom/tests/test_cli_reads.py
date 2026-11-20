"""CLI reads for a signed-in site (PPY-808255, PPY-3b3f50, PPY-83e413): reference show, unknown corpora, corpus keys, stories list,
assignments show, section names, and a publish on a lane with no amplify_outputs.json. Every client is an in-memory fake."""

from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

import fake_client  # noqa: E402
from papyrus.operator.backends.cloud import CloudBackend  # noqa: E402
from papyrus.operator.commands import references as reference_commands  # noqa: E402
from papyrus.operator.config import OperatorConfig  # noqa: E402
from papyrus.operator.errors import OperatorError  # noqa: E402
from papyrus_content import assignments_commands, projection_trigger, publication, steering, story_commands, story_reporting  # noqa: E402

fake_client.INDEX_MODELS.setdefault("itemsByStage", "Item")
fake_client.INDEX_MODELS.setdefault("knowledgeCorporaByRoleAndName", "KnowledgeCorpus")


class Client(fake_client.FakeAuthoringClient):
    tenant_id = None
    endpoint = "https://example.test/graphql"

    def safe_list_records(self, model_name):
        return self.list_records(model_name)

    def get_records_by_id(self, model_name, record_ids):
        return {record_id: self.tables[model_name][record_id] for record_id in record_ids if record_id in self.tables.get(model_name, {})}


def corpus(key, role="canonical"):
    return {"id": f"knowledge-corpus-{key}", "name": key.title(), "role": role}


def reference(identifier="ref-1-v1", lineage="ref-1", corpus_key="ai-ml-research"):
    return {"id": identifier, "lineageId": lineage, "versionNumber": 1, "versionState": "current", "title": "A source",
            "curationStatus": "accepted", "corpusId": f"knowledge-corpus-{corpus_key}", "sourceUri": "https://example.test/a"}


def backend(client):
    config = OperatorConfig(backend="cloud", default_corpus_key=None, publication_key=None, pod_path=None, default_story=None,
                            graphql_endpoint=None, config_path=None, fixture_root=None)
    patches = (mock.patch("papyrus_content.graphql_authoring.create_authoring_client", return_value=(client, {})),
               mock.patch.object(CloudBackend, "_ensure_auth"))
    return CloudBackend(config), patches


def run(callable_, *args, **kwargs):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        callable_(*args, **kwargs)
    return out.getvalue()


# --- references show -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("given", ["ref-1-v1", "ref-1"])
def test_show_takes_the_item_id_and_the_lineage_id_that_stories_show_prints(given):
    cloud, patches = backend(Client({"Reference": [reference()]}))
    with patches[0], patches[1]:
        row = cloud.show_reference(given)
    assert row.identifier == "ref-1-v1" and row.extra["lineageId"] == "ref-1" and row.extra["corpus"] == "ai-ml-research"


def test_show_honours_a_corpus_key_that_matches():
    cloud, patches = backend(Client({"Reference": [reference()]}))
    with patches[0], patches[1]:
        assert cloud.show_reference("ref-1", "ai-ml-research").identifier == "ref-1-v1"


def test_show_with_the_wrong_corpus_key_says_where_the_reference_is():
    cloud, patches = backend(Client({"Reference": [reference()]}))
    with patches[0], patches[1], pytest.raises(OperatorError, match="in corpus ai-ml-research, not threat-intelligence"):
        cloud.show_reference("ref-1", "threat-intelligence")


def test_show_of_an_unknown_reference_is_an_error():
    cloud, patches = backend(Client({"Reference": [reference()]}))
    with patches[0], patches[1], pytest.raises(OperatorError, match="Reference not found: nope"):
        cloud.show_reference("nope")


def test_the_show_command_passes_the_corpus_key_without_the_record_prefix():
    seen = []
    fake = mock.Mock()
    fake.show_reference.side_effect = lambda ref, key: seen.append((ref, key)) or reference_row()
    config = OperatorConfig("cloud", None, None, None, None, None, None, None)
    with mock.patch.object(reference_commands, "create_backend", return_value=fake), contextlib.redirect_stdout(io.StringIO()):
        reference_commands.run_references_show(config, ["ref-1", "--corpus-key", "knowledge-corpus-ai-ml-research"])
    assert seen == [("ref-1", "ai-ml-research")]


def _shown_reference_ids(flags):
    seen = []
    fake = mock.Mock()
    fake.show_reference.side_effect = lambda ref, key: seen.append(ref) or reference_row()
    config = OperatorConfig("cloud", None, None, None, None, None, None, None)
    with mock.patch.object(reference_commands, "create_backend", return_value=fake), contextlib.redirect_stdout(io.StringIO()):
        reference_commands.run_references_show(config, flags)
    return seen


@pytest.mark.parametrize("flags, expected", [
    (["ref-1-v1"], "ref-1-v1"),
    (["--reference", "ref-1-v1"], "ref-1-v1"),
    (["--reference=ref-1"], "ref-1"),
    (["ref-1", "--backend", "cloud"], "ref-1"),
])
def test_show_takes_the_id_positionally_or_after_reference(flags, expected):
    assert _shown_reference_ids(flags) == [expected]


@pytest.mark.parametrize("flags, message", [
    ([], "requires a Reference id"),
    (["--backend", "cloud"], "requires a Reference id"),
    (["--reference"], "--reference requires a Reference id"),
    (["--reference", "a", "b"], "takes one Reference id, got 2"),
    (["ref-1", "--refrence", "ref-1"], "does not take --refrence"),
])
def test_show_fails_loudly_on_a_missing_id_two_ids_or_an_unknown_flag(flags, message):
    with pytest.raises(OperatorError, match=message) as raised:
        _shown_reference_ids(flags)
    assert raised.value.exit_code == 2


@pytest.mark.parametrize("flags, message", [
    ([], "requires a Reference id"),
    (["--reference", "ref-1", "--offest", "5"], "does not take --offest"),
    (["ref-1", "--reference", "ref-2"], "takes one Reference id, got 2"),
])
def test_text_fails_loudly_on_a_missing_id_two_ids_or_an_unknown_flag(flags, message):
    config = OperatorConfig("cloud", None, None, None, None, None, None, None)
    with pytest.raises(OperatorError, match=message) as raised:
        reference_commands.run_references_text(config, flags)
    assert raised.value.exit_code == 2


@pytest.mark.parametrize("flags", [["ref-1"], ["--reference", "ref-1"], ["ref-1-v1"]])
def test_text_resolves_a_lineage_id_or_a_record_id_to_the_current_version(flags):
    from papyrus_content import reference_text_read

    client = Client({"Reference": [reference()]})
    seen = []
    config = OperatorConfig("cloud", None, None, None, None, None, None, None)
    fake = mock.Mock(spec=["_ensure_auth"])

    def read(client_, reference_id, **kwargs):
        seen.append(story_reporting.current_reference(client_, reference_id)["id"])
        return {"referenceId": "ref-1-v1", "url": "u", "source": "s", "sourceKind": None, "capturedAt": None, "totalCharacters": 1, "offset": 0,
                "returnedCharacters": 1, "truncated": False, "flags": [], "nextOffset": None, "text": "x"}

    with mock.patch.object(reference_commands, "create_backend", return_value=fake), \
         mock.patch("papyrus_content.graphql_authoring.create_authoring_client", return_value=(client, {})), \
         mock.patch.object(reference_text_read, "read_reference_text", side_effect=read), contextlib.redirect_stdout(io.StringIO()):
        assert reference_commands.run_references_text(config, flags) == 0
    assert seen == ["ref-1-v1"]


def reference_row():
    from papyrus.operator.output import OperatorRow
    return OperatorRow(kind="cloud-reference", status="", identifier="ref-1-v1", title="A", extra={})


# --- unknown corpus --------------------------------------------------------------------------------------------------

def list_with(client, key):
    cloud, patches = backend(client)
    with patches[0], patches[1], mock.patch("papyrus_newsroom.reference_curation_signals.reference_list", return_value={"items": []}):
        return cloud.list_references(corpus_key=key, limit=5, status="", order="newest")


def test_an_empty_list_for_a_corpus_that_does_not_exist_is_an_error_naming_the_sites_corpus():
    with pytest.raises(OperatorError, match="Unknown corpus nonsense.*This site serves ai-ml-research"):
        list_with(Client({"KnowledgeCorpus": [corpus("ai-ml-research")]}), "nonsense")


def test_an_empty_list_for_a_corpus_that_exists_is_an_empty_list():
    assert list_with(Client({"KnowledgeCorpus": [corpus("ai-ml-research")]}), "ai-ml-research") == []


def test_the_record_id_of_a_corpus_means_its_key():
    assert publication.normalize_corpus_key("knowledge-corpus-ai-ml-research") == "ai-ml-research"
    assert publication.normalize_corpus_key("ai-ml-research") == "ai-ml-research"


# --- create-from-catalog corpus key ----------------------------------------------------------------------------------

STEERING = {"corpora": [{"key": "threat-intelligence", "name": "TI", "role": "canonical"}]}


def resolve(options, hosted=("ai-ml-research",), steering_config=STEERING):
    return publication.resolve_catalog_corpus(Client({"KnowledgeCorpus": [corpus(key) for key in hosted]}), options, lambda path: steering_config)


def test_a_key_the_steering_file_does_not_list_is_checked_against_the_sites_own_corpus():
    config, _ = resolve({"corpus-key": "ai-ml-research"})
    assert config["key"] == "ai-ml-research"


def test_the_record_id_form_of_the_key_is_accepted():
    config, _ = resolve({"corpus-key": "knowledge-corpus-ai-ml-research"})
    assert config["key"] == "ai-ml-research"


def test_a_key_that_is_neither_listed_nor_the_sites_corpus_fails_naming_the_real_one():
    with pytest.raises(ValueError, match="does not match the hosted canonical corpus ai-ml-research"):
        resolve({"corpus-key": "nonsense"})


def test_a_key_the_steering_file_lists_is_still_governed_by_it():
    config, _ = resolve({"corpus-key": "threat-intelligence"})
    assert config["name"] == "TI"


# --- the Papyrus source tree is not a site's choice ------------------------------------------------------------------

def test_the_papyrus_source_tree_steering_file_is_not_a_site_choice(tmp_path, monkeypatch):
    monkeypatch.delenv("PAPYRUS_STEERING_CONFIG", raising=False)
    (tmp_path / "corpora").mkdir()
    (tmp_path / "corpora" / "papyrus-steering.yml").write_text("x: 1\n")
    monkeypatch.setattr(steering, "PAPYRUS_ROOT", tmp_path)
    monkeypatch.setattr(steering, "resolve_topics_steering_config_path", lambda: "corpora/papyrus-steering.yml")
    assert steering.steering_config_chosen_by_site() is True   # a site's own checkout
    (tmp_path / "pyproject.toml").write_text("")
    (tmp_path / "src" / "papyrus_content").mkdir(parents=True)
    (tmp_path / "src" / "papyrus").mkdir()
    assert steering.steering_config_chosen_by_site() is False   # the product's source tree
    monkeypatch.setenv("PAPYRUS_STEERING_CONFIG", str(tmp_path / "mine.yml"))
    assert steering.steering_config_chosen_by_site() is True    # an explicit choice always counts


# --- stories list, assignments show ----------------------------------------------------------------------------------

def story(lineage, stage, section="news", updated="2026-11-01", **extra):
    return {"id": f"{lineage}-v1", "lineageId": lineage, "versionNumber": 1, "versionState": "current", "stage": stage,
            "section": section, "title": f"Title {lineage}", "type": "untyped", "updatedAt": updated, **extra}


def stories_client():
    return Client({"Item": [story("a", "idea", updated="2026-11-01"), story("b", "reporting", updated="2026-11-03"),
                            story("c", "spiked"), story("d", "idea", section="other"), story("w", "idea", type="wiki_page")],
                   "NewsroomSection": [{"id": "news", "title": "News Desk"}, {"id": "other", "title": "Other"}]})


def list_stories(*flags):
    with mock.patch.object(story_commands, "create_authoring_client", return_value=(stories_client(), {})):
        return run(story_commands.stories_list, list(flags))


def test_stories_list_prints_lineage_ids_newest_first_without_spiked_or_system_pages():
    lines = [line.split("\t") for line in list_stories().splitlines()]
    assert [line[2] for line in lines[:-1]] == ["b", "a", "d"] and lines[0][3] == "reporting"


def test_stories_list_filters_by_stage_and_by_section_name():
    assert [line.split("\t")[2] for line in list_stories("--stage", "idea", "--section", "News Desk").splitlines()[:-1]] == ["a"]


def test_stories_list_of_an_unknown_section_is_an_error():
    with pytest.raises(ValueError, match="Unknown NewsroomSection"):
        list_stories("--section", "nonsense")


def test_assignments_show_prints_the_fields_and_the_events():
    client = Client({"Assignment": [{"id": "as-1", "status": "open", "assignmentTypeKey": "research.multi", "title": "Look", "queueKey": "q",
                                     "sectionKey": "news", "itemLineageId": "a", "assigneeKey": "someone"}],
                     "AssignmentEvent": [{"id": "e1", "assignmentId": "as-1", "eventType": "created", "createdAt": "2026-11-01", "toStatus": "open"}]})
    with mock.patch.object(assignments_commands, "create_authoring_client", return_value=(client, {})):
        out = run(assignments_commands.assignments_show, ["--assignment", "as-1"])
    assert "assignments\tshow\tas-1\tstatus\topen" in out and "\tstory\ta" in out and "\theld by\tsomeone" in out
    assert "created" in out and "assignments\tevents\tas-1\t1" in out


def test_assignments_show_of_a_missing_assignment_is_an_error():
    with mock.patch.object(assignments_commands, "create_authoring_client", return_value=(Client(), {})), pytest.raises(ValueError, match="Assignment not found: x"):
        assignments_commands.assignments_show(["--assignment", "x"])


# --- section by name -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("given", ["news", "News Desk"])
def test_stories_create_takes_the_section_id_or_its_name_and_stores_the_id(given):
    client = Client({"NewsroomSection": [{"id": "news", "title": "News Desk"}]})
    item = story_reporting.create_story(client, title="T", section_key=given, actor="a")
    assert item["section"] == "news"


def test_stories_create_with_an_unknown_section_is_an_error():
    with pytest.raises(ValueError, match="Unknown NewsroomSection nonsense"):
        story_reporting.create_story(Client({"NewsroomSection": [{"id": "news", "title": "News Desk"}]}), title="T", section_key="nonsense", actor="a")


# --- publish with no amplify_outputs.json ----------------------------------------------------------------------------

def test_a_signed_in_publish_with_no_outputs_file_asks_the_newsroom_to_project(monkeypatch):
    monkeypatch.delenv(projection_trigger.PUBLICATION_KIND_ENV, raising=False)
    with mock.patch("papyrus_content.env.load_amplify_outputs", side_effect=ValueError("none")), \
            mock.patch("papyrus_content.user_auth_mode.user_auth_requested", return_value=True):
        assert projection_trigger.projection_enabled() is False
        assert projection_trigger.projection_unknown() is True and projection_trigger.projection_requested() is True


def test_an_outputs_file_that_belongs_to_the_site_still_decides():
    outputs = {"custom": {"publication": {"kind": "next"}}}
    with mock.patch("papyrus_content.env.load_amplify_outputs", return_value=outputs), \
            mock.patch("papyrus_content.env.outputs_belong_to_selection", return_value=True), \
            mock.patch("papyrus_content.user_auth_mode.user_auth_requested", return_value=True):
        assert projection_trigger.projection_unknown() is False and projection_trigger.projection_requested() is False


def test_another_sites_outputs_file_never_decides_for_the_chosen_site():
    outputs = {"custom": {"publication": {"kind": projection_trigger.S3_PROJECTION_KIND}}}
    with mock.patch("papyrus_content.env.load_amplify_outputs", return_value=outputs), \
            mock.patch("papyrus_content.env.outputs_belong_to_selection", return_value=False), \
            mock.patch("papyrus_content.user_auth_mode.user_auth_requested", return_value=True):
        assert projection_trigger.site_publication() == {} and projection_trigger.projection_unknown() is True


def test_the_iam_lane_is_never_unknown():
    with mock.patch("papyrus_content.env.load_amplify_outputs", side_effect=ValueError("none")), \
            mock.patch("papyrus_content.user_auth_mode.user_auth_requested", return_value=False):
        assert projection_trigger.projection_unknown() is False
