"""A Reference titled with its own web address takes its page's real title: the rule, every writer, the repair command and the public card. No network, no AWS."""
from __future__ import annotations

import io
import json
from datetime import datetime, timezone

import pytest

from papyrus_content import reference_titles as titles
from papyrus_content import references_titles as repair
from papyrus_content.home_page.export import public_reference
from papyrus_content.home_page.settings import home_page_settings_from_mapping
from papyrus_content.link_exploration import Exploration, PageMetadata
from papyrus_content.reference_curation_store import CurationError, correct_reference_capture
from papyrus_content.reference_images import attach_preview, preview_attachment_id

CORPUS = "knowledge-corpus-demo"
ADDRESS = "https://labs.example.org/research/csa-research-note-ai-coding-assistant-attack-surface/"
PAGE_TITLE = "AI Coding Assistants as Attack Surface"
NOW = datetime(2026, 11, 5, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _undo_the_signed_in_lane_switch(monkeypatch):
    monkeypatch.setenv("PAPYRUS_GRAPHQL_AUTH", "iam")


class Site:
    """References, attachments and the capture action, in memory."""

    def __init__(self, rows=(), attachments=None):
        self.rows = {row["id"]: row for row in rows}
        self.attachments = dict(attachments or {})
        self.updates: list[dict] = []
        self.actions: list[dict] = []
        self.old_backend = False

    def get_record(self, model, record_id):
        return (self.rows if model == "Reference" else self.attachments).get(record_id)

    def update_record(self, model, payload):
        assert model == "Reference"
        self.updates.append(payload)
        self.rows[payload["id"]].update(payload)

    def upsert(self, model, row):
        self.attachments[row["id"]] = row

    def list_records(self, model):
        return [{"id": CORPUS}]

    def iterate_newest_first(self, index, partition):
        assert index == "referencesByFeedStateAndArrival"
        yield from sorted((dict(row) for row in self.rows.values() if row.get("feedStateKey") == partition), key=lambda row: row["feedArrivalAt"], reverse=True)

    def graphql(self, query, variables):
        assert "correctReferenceCapture" in query
        payload = json.loads(variables["input"])
        self.actions.append(payload)
        if self.old_backend:
            return {"correctReferenceCapture": json.dumps({"ok": False, "errors": [{"message": "Unsupported correction fields; the editor is taken from the signed-in session."}]})}
        try:
            answer = correct_reference_capture(self, payload, {"username": "editor"})
        except CurationError as error:
            return {"correctReferenceCapture": json.dumps({"ok": False, "errors": [{"message": str(error)}]})}
        return {"correctReferenceCapture": json.dumps(answer)}


def reference(identifier="a", title=ADDRESS, status="pending", address=None, **extra) -> dict:
    return {"id": f"reference-{identifier}-v1", "lineageId": f"reference-{identifier}", "title": title, "sourceUri": address or ADDRESS.replace("research/", f"research/{identifier}-"),
            "curationStatus": status, "feedStateKey": f"{CORPUS}#{'rated' if status != 'pending' else 'unrated'}", "feedArrivalAt": f"2026-11-0{1 + ord(identifier) % 4}T00:00:00.000Z",
            "versionNumber": 1, **extra}


def preview_row(row, **metadata):
    return {"id": preview_attachment_id(row), "metadata": json.dumps(metadata)}


# --- the rule --------------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("value,expected", [(ADDRESS, True), ("  http://example.org/a  ", True), ("", False), ("A real title", False),
                                            ("https://example.org is a site", False), (None, False)])
def test_only_a_whole_address_counts_as_an_address(value, expected):
    assert titles.is_address(value) is expected


def test_a_title_is_replaceable_only_while_empty_or_an_address():
    assert titles.needs_title({"title": ADDRESS}) and titles.needs_title({"title": ""}) and titles.needs_title({})
    assert not titles.needs_title({"title": "An editor's own wording"})


@pytest.mark.parametrize("value", [None, "", "   ", ADDRESS, "Just a moment...", "Attention Required! | Cloudflare", "403 Forbidden", 12])
def test_an_address_an_empty_title_or_a_bot_walls_title_is_not_a_page_title(value):
    assert titles.usable_title(value) is None


def test_a_page_title_is_whitespace_collapsed_and_bounded():
    assert titles.usable_title("  GitHub -\n  owner/repo \t ") == "GitHub - owner/repo"
    assert len(titles.usable_title("x" * 900)) == titles.MAXIMUM_TITLE_CHARACTERS


def test_a_title_set_in_the_meantime_is_never_overwritten():
    row = reference()
    site = Site([row])
    site.rows[row["id"]]["title"] = "Set by an editor a moment ago"
    assert titles.record_page_title(site, dict(row), PAGE_TITLE) == "kept"
    assert site.updates == []


def test_the_page_title_replaces_an_address_once():
    row = reference()
    site = Site([row])
    assert titles.record_page_title(site, row, PAGE_TITLE) == "set"
    assert titles.record_page_title(site, row, "A later page title") == "kept"
    assert [update for update in site.updates if "title" in update] == [{"id": row["id"], "title": PAGE_TITLE}]   # and the card copies, in their own update (PPY-7f1e54)


# --- the readable stand-in -------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("address,site_name,expected", [
    ("https://labs.example.org/research/ai-coding-attack-surface-2026/", "Lab Space", "Lab Space: ai coding attack surface 2026"),
    ("https://www.example.org/", None, "example.org"),
    ("https://docs.example.org/guide/Getting%20Started.html", None, "docs.example.org: Getting Started"),
    ("https://example.org/news/12345", None, "example.org: news"),
    ("https://example.org/12345", None, "example.org"),
    ("https://example.org/papers/some_paper.pdf?download=1", "Example", "Example: some paper"),
])
def test_the_stand_in_is_the_site_and_the_words_of_the_address(address, site_name, expected):
    assert titles.readable_name(address, site_name) == expected


# --- when a Reference is created or captured -------------------------------------------------------------------------------------------------


def explored(title=PAGE_TITLE, site_name="Lab Space"):
    return Exploration(True, ADDRESS, via="direct", metadata=PageMetadata(image_url="https://img.example.org/a.png", description="d", site_name=site_name, title=title))


def test_a_new_reference_takes_the_title_its_preview_page_declared():
    row = reference()
    site = Site([row])
    assert attach_preview(site, row, exploration=explored(), now=lambda: NOW, log=lambda line: None) == "written"
    assert site.rows[row["id"]]["title"] == PAGE_TITLE
    assert [update for update in site.updates if "title" in update] == [{"id": row["id"], "title": PAGE_TITLE}]   # and the card copies, in their own update (PPY-7f1e54)


def test_a_new_reference_with_a_real_title_keeps_it():
    row = reference(title="The editor's title")
    site = Site([row])
    attach_preview(site, row, exploration=explored(), now=lambda: NOW, log=lambda line: None)
    assert not [update for update in site.updates if "title" in update] and row["title"] == "The editor's title"


def test_a_page_with_no_title_leaves_the_address_and_still_gets_its_preview():
    row = reference()
    site = Site([row])
    assert attach_preview(site, row, exploration=explored(title=None), now=lambda: NOW, log=lambda line: None) == "written"
    assert not [update for update in site.updates if "title" in update] and preview_attachment_id(row) in site.attachments


def test_a_title_write_that_fails_never_fails_the_preview():
    row = reference()
    site = Site([row])
    site.update_record = lambda model, payload: (_ for _ in ()).throw(RuntimeError("write refused"))
    lines: list[str] = []
    assert attach_preview(site, row, exploration=explored(), now=lambda: NOW, log=lines.append) == "written"
    assert any('"referenceTitle": "failed"' in line for line in lines)


# --- the action the repair uses --------------------------------------------------------------------------------------------------------------


def test_the_capture_action_sets_a_title_only_on_a_reference_titled_with_an_address():
    row = reference()
    site = Site([row])
    assert correct_reference_capture(site, {"referenceId": row["id"], "pageTitle": PAGE_TITLE}, {"username": "e"}) == {
        "ok": True, "referenceId": row["id"], "title": PAGE_TITLE, "changed": True}
    again = correct_reference_capture(site, {"referenceId": row["id"], "pageTitle": "Another"}, {"username": "e"})
    assert again["changed"] is False and again["title"] == PAGE_TITLE


@pytest.mark.parametrize("arguments", [{"pageTitle": ADDRESS}, {"pageTitle": "Just a moment..."}, {"pageTitle": 7}, {"pageTitle": "T", "text": "body"}])
def test_the_capture_action_refuses_what_is_not_a_page_title(arguments):
    row = reference()
    with pytest.raises(CurationError):
        correct_reference_capture(Site([row]), {"referenceId": row["id"], **arguments}, {"username": "e"})


# --- the repair command ----------------------------------------------------------------------------------------------------------------------


def run(site, *flags, explorer=None):
    out, errors = io.StringIO(), io.StringIO()
    import sys
    real, sys.stderr = sys.stderr, errors
    try:
        code = repair.command(["--corpus-key", "demo", *flags], client=site, out=out, explorer=explorer, sleep=lambda seconds: None)
    finally:
        sys.stderr = real
    return code, out.getvalue(), errors.getvalue()


def three_rows():
    with_preview, with_card, bare = reference("a"), reference("b", status="accepted"), reference("c")
    plain = reference("d", title="Already titled")
    card = {"id": "reference-attachment-card", "metadata": json.dumps({"kind": "reference-curation", "page": {"title": "From the capture card"}})}
    from papyrus_content.reference_curation_store import card_id
    site = Site([with_preview, with_card, bare, plain], {preview_attachment_id(with_preview): preview_row(with_preview, title="From the preview"),
                                                         card_id(with_card): {**card, "id": card_id(with_card)},
                                                         preview_attachment_id(bare): preview_row(bare, description="no title here")})
    return site, with_preview, with_card, bare, plain


def test_the_preview_counts_what_is_fixable_without_a_fetch_and_writes_nothing():
    site, *_ = three_rows()
    code, out, _ = run(site)
    assert code == 0 and site.updates == [] and site.actions == []
    assert "would_set 2" in out and "would_fetch 1" in out and "preview" in out
    assert "Already titled" not in out


def test_write_records_the_stored_titles_and_leaves_the_rest_for_a_fetch():
    site, with_preview, with_card, bare, plain = three_rows()
    code, out, _ = run(site, "--write")
    assert code == 0
    assert site.rows[with_preview["id"]]["title"] == "From the preview" and site.rows[with_card["id"]]["title"] == "From the capture card"
    assert titles.is_address(site.rows[bare["id"]]["title"]) and site.rows[plain["id"]]["title"] == "Already titled"
    assert "set 2" in out and "needs_fetch 1" in out


def test_fetch_reads_only_the_pages_with_no_stored_title_and_says_what_a_blocked_page_shows():
    site, _, _, bare, _ = three_rows()
    asked: list[str] = []

    def explorer(address, **options):
        asked.append(address)
        return Exploration(False, address, failure="blocked")

    code, out, _ = run(site, "--write", "--fetch", explorer=explorer)
    assert code == 0 and asked == [bare["sourceUri"]]
    assert "no_title 1" in out and "page not readable: blocked" in out and "the card shows 'labs.example.org: c csa research note" in out
    assert titles.is_address(site.rows[bare["id"]]["title"])


def test_a_fetched_title_is_recorded():
    site, _, _, bare, _ = three_rows()
    run(site, "--write", "--fetch", explorer=lambda address, **o: explored(title="Fetched title"))
    assert site.rows[bare["id"]]["title"] == "Fetched title"


def test_a_second_run_has_nothing_left_for_the_titles_already_repaired():
    site, *_ = three_rows()
    run(site, "--write")
    before = len(site.updates)
    _, out, _ = run(site, "--write")
    assert len(site.updates) == before and "needs_fetch 1" in out and "set" not in out.split("done")[1]


def test_fetch_without_write_is_refused():
    site, *_ = three_rows()
    code, _, errors = run(site, "--fetch")
    assert code == 2 and "only goes with --write" in errors


def test_an_old_backend_stops_the_run_with_the_advice_to_deploy_first():
    site, *_ = three_rows()
    site.old_backend = True
    code, _, errors = run(site, "--write")
    assert code == 2 and "deploy the site first" in errors and site.updates == []


def test_rejected_references_are_left_alone_unless_asked_for():
    rejected = reference("e", status="rejected")
    site = Site([rejected], {preview_attachment_id(rejected): preview_row(rejected, title="Rejected page")})
    _, out, _ = run(site)
    assert "no References" in out
    _, out, _ = run(site, "--status", "all")
    assert "would_set 1" in out


# --- the public card -------------------------------------------------------------------------------------------------------------------------


SETTINGS = home_page_settings_from_mapping({"references": {"corpus": CORPUS}})


def card_title(title, preview=None, address=ADDRESS):
    row = {**reference(title=title, status="accepted"), "lineageId": "reference-x", "sourceUri": address, "curationActorKind": "human"}
    return public_reference(row, None, preview, {}, SETTINGS)["title"]


def test_the_card_shows_the_stored_preview_title_when_the_reference_title_is_an_address():
    assert card_title(ADDRESS, preview_row(reference(), title=PAGE_TITLE, siteName="Lab Space")) == PAGE_TITLE


def test_the_card_shows_a_readable_name_not_the_address_when_no_title_is_known():
    shown = card_title(ADDRESS, preview_row(reference(), siteName="Lab Space"))
    assert shown == "Lab Space: csa research note ai coding assistant attack surface"
    assert not titles.is_address(card_title(ADDRESS, None))


def test_a_real_title_is_shown_as_it_is():
    assert card_title("The editor's title", preview_row(reference(), title="Other")) == "The editor's title"


# --- when capture runs (curation) ------------------------------------------------------------------------------------------------------------


def curated_title(title):
    from curation_support import MemoryClient, article_html, page, reference as curation_reference, services
    from papyrus_content import reference_curation as curation

    address = "https://news.example.org/r1"
    ref = curation_reference(title=title, sourceUri=address)
    client = MemoryClient([ref])
    curation.curate_reference(client, ref, services=services(client, pages={address: page(article_html())}))
    return client.get_record("Reference", ref["id"])["title"]


def test_capture_gives_a_reference_titled_with_its_address_the_page_title():
    assert curated_title("https://news.example.org/r1") == "Transit plan"


def test_capture_never_replaces_a_title_that_is_not_an_address():
    assert curated_title("Title chosen by an editor") == "Title chosen by an editor"
