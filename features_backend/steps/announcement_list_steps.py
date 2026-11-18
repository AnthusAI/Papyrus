"""The Announcements list, a Story's lines and ``explain`` (features_backend/announcement-list-*.feature, announcement-explain.feature, PPY-e4ae3a).

Every question goes through the entry a site uses: the image operation table's ``execute`` (the console door and the agents' tools) or ``papyrus announcements ...``
(``announcements.cli.command``) with the list handlers, over the in-memory records of the records specs. The catalog, the clock, the policy and the Stories' facts come from
announcement_records_steps.py and announcement_review_steps.py; this file adds the Story rows ``explain`` reads, the settings document, and the questions.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any

import parse
from behave import given, register_type, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.announcements import blocked_drafts, list_handlers  # noqa: E402
from papyrus_content.announcements import cli as announcements_cli  # noqa: E402
from papyrus_content.announcements.decisions import Announcements  # noqa: E402
from papyrus_content.announcements.deliveries import Deliveries  # noqa: E402
from papyrus_content.announcements.fakes import FakeBackend  # noqa: E402
from papyrus_content.announcements.records_fakes import MemoryDeliveryFiles, RecordsBackend  # noqa: E402
from papyrus_content.images.handlers import Caller, execute  # noqa: E402

TENANT = "alpha"
PERSON = Caller(kind="person", subject="ellie", is_admin=False)


@parse.with_pattern(r'[^"]*')
def _quoted(text):
    return text


register_type(L=_quoted)


class StoryBackend(RecordsBackend):
    """The records backend that also holds Story versions, so ``explain`` can read a Story: the two indexes a Story read uses, and ``Item`` and ``PublishedItem`` rows."""

    tenant_id = TENANT

    def __init__(self) -> None:
        super().__init__()
        self.items = self.records.setdefault("Item", {})
        self.published = self.records.setdefault("PublishedItem", {})

    def list_by_index(self, index: str, key: str, **options: Any) -> list[dict[str, Any]]:
        if index == "itemsByLineageAndVersion":
            self.reads.append((index, key))
            return [dict(row) for row in self.items.values() if row["lineageId"] == key]
        if index == "knowledgeCorporaByRoleAndName":
            return [{"id": "knowledge-corpus-mom", "name": "Machines on Machines", "role": "canonical"}]
        return super().list_by_index(index, key, **options)

    add_story = FakeBackend.add_story


class Settings:
    """The site's announcement settings document and X connection, as the site's function serves them."""

    def __init__(self, mode: str = "dry_run", min_stars: int = 3, require_reviewed: bool = False) -> None:
        self.document = {"mode": mode, "rules": {"minStars": min_stars, "storyTypes": ["article"], "sections": [], "requireReviewedSource": require_reviewed}, "budget": 10,
                         "billingCycleDay": 1, "prices": {}, "labelConfirmed": True, "pause": {"paused": False}}

    def read(self) -> dict:
        return self.document

    def status(self) -> dict:
        return {"connection": "connected", "accountId": "handle-1", "handle": "@handle_one"}


def _backend(context) -> StoryBackend:
    if not isinstance(context.backend, StoryBackend):
        raise AssertionError('Start the scenario with: Given an empty announcement catalog that knows its Stories')
    return context.backend


@given("an empty announcement catalog that knows its Stories")
def catalog_with_stories(context):
    context.execute_steps("Given an empty announcement catalog")
    context.backend = backend = StoryBackend()
    context.files = MemoryDeliveryFiles(backend)
    context.deliveries = Deliveries(backend, context.files)
    context.announcements = Announcements(backend, context.deliveries)
    context.settings = Settings()
    context.reads_before = 0


@given('the Story "{lineage:L}" is published and titled "{title:L}" with {stars:d} stars given by "{who:L}"')
def published_story(context, lineage, title, stars, who):
    backend = _backend(context)
    backend.add_story(lineage, stars=stars, title=title)
    backend.items[f"{lineage}-v1"]["starRatedBy"] = who


@given('the Story "{lineage:L}" is published and titled "{title:L}" and unrated')
def unrated_story(context, lineage, title):
    _backend(context).add_story(lineage, stars=None, title=title)


@given('the Story "{lineage:L}" is a draft with {stars:d} stars given by "{who:L}"')
def draft_story(context, lineage, stars, who):
    backend = _backend(context)
    backend.add_story(lineage, stars=stars, published=False)
    backend.items[f"{lineage}-v1"]["starRatedBy"] = who


@given('the Story "{lineage:L}" is a "{story_type:L}"')
def story_is_type(context, lineage, story_type):
    _backend(context).items[f"{lineage}-v1"]["type"] = story_type


@given('the publication announces in "{mode:L}" mode from {stars:d} stars')
def settings_are(context, mode, stars):
    context.settings = Settings(mode, stars, context.require_reviewed)


@given('the Story "{lineage:L}" has the title "{title:L}" at version {version:d}')
def story_row(context, lineage, title, version):
    """The Item row the list reads a title from: the version the Announcement looked at."""
    _backend(context).items[f"{lineage}-v{version}"] = {"id": f"{lineage}-v{version}", "lineageId": lineage, "versionNumber": version, "title": title}


# --- the door ---------------------------------------------------------------------------------------------------------------------------------------


def handlers(context):
    list_handlers._publication = lambda client: "publication"   # the publication's key is read from the site's own record, which these specs do not build
    return list_handlers.signed_in_handlers(client_factory=lambda: context.backend, policy_factory=lambda client: context.policy, clock=lambda: context.now,
                                            functions=getattr(context, "settings", None) or Settings(),
                                            stamps=lambda client: context.stamps)


def ask(context, name, arguments):
    context.reads_before = len(context.backend.reads)
    context.writes_before = len(context.backend.writes)
    context.envelope = execute(name, arguments, PERSON, handlers(context))
    assert context.envelope["ok"], context.envelope
    context.result = context.envelope["result"]
    return context.result


@when('the Story "{lineage:L}" is read through the door for where it was announced')
def story_through_door(context, lineage):
    ask(context, "announcements_where", {"story": lineage})


@when("the Announcements list is read through the door")
def list_through_door(context):
    ask(context, "announcements_recent", {})


@when("the Announcements list is read through the door in pages of {size:d}")
def list_pages(context, size):
    context.pages = []
    before = None
    while True:
        page = ask(context, "announcements_recent", {"limit": size, **({"before": before} if before else {})})
        context.pages.append(page)
        before = page["next"]
        if not before:
            break
    context.result = context.pages[0]


def _run_cli(context, argv):
    context.reads_before = len(context.backend.reads)
    context.writes_before = len(context.backend.writes)
    out = io.StringIO()
    code = announcements_cli.command(argv, handlers=handlers(context), environ={}, stdout=out)
    context.exit_code = code
    context.envelope = json.loads(out.getvalue())
    context.result = context.envelope.get("result") or {}


@when('a person types "papyrus announcements explain --story {lineage:L}"')
def type_explain(context, lineage):
    _run_cli(context, ["explain", "--story", lineage])


# --- reading what was answered ----------------------------------------------------------------------------------------------------------------------


def _entries(context):
    return context.result["announcements"]


def _line(context, channel, account):
    lines = [line for entry in _entries(context) for line in entry["deliveries"] if line["channel"] == channel and line["accountId"] == account]
    assert lines, f"no line for {channel} {account} in {_entries(context)}"
    return lines[0]


def _overdue(context, channel, account):
    return [line for line in context.result["overdue"] if line["channel"] == channel and line["accountId"] == account]


@then("the answer holds {count:d} Announcement")
@then("the answer holds {count:d} Announcements")
def answer_count(context, count):
    assert len(_entries(context)) == count, _entries(context)


@then('the line for "{channel:L}" "{account:L}" reads "{words:L}" with the mark "{mark:L}"')
def line_reads(context, channel, account, words, mark):
    line = _line(context, channel, account)
    assert line["words"] == words and line["mark"] == mark, line


@then('the line for "{channel:L}" "{account:L}" says "{words:L}" with the mark "{mark:L}"')
def line_says(context, channel, account, words, mark):
    line = _line(context, channel, account)
    found = [item for item in line["attention"] if item["words"] == words and item["mark"] == mark]
    assert found, line["attention"]


@then('the line for "{channel:L}" "{account:L}" does not say "{words:L}"')
def line_does_not_say(context, channel, account, words):
    line = _line(context, channel, account)
    assert not [item for item in line["attention"] if item["words"] == words], line["attention"]


@then('the line for "{channel:L}" "{account:L}" shows the review "{words:L}" with the mark "{mark:L}"')
def line_review(context, channel, account, words, mark):
    approval = _line(context, channel, account)["approval"]
    assert approval and approval["words"].startswith(words) and approval["mark"] == mark, approval


@then('the line for "{channel:L}" "{account:L}" shows no review')
def line_no_review(context, channel, account):
    assert _line(context, channel, account)["approval"] is None


@then('the overdue list holds the Delivery "{channel:L}" "{account:L}"')
def overdue_holds(context, channel, account):
    assert _overdue(context, channel, account), context.result["overdue"]


@then('the overdue list does not hold the Delivery "{channel:L}" "{account:L}"')
def overdue_does_not_hold(context, channel, account):
    assert not _overdue(context, channel, account), context.result["overdue"]


@then('the overdue list holds {count:d} Deliveries')
@then('the overdue list holds {count:d} Delivery')
def overdue_count(context, count):
    assert len(context.result["overdue"]) == count, context.result["overdue"]


@then('the line for "{channel:L}" "{account:L}" shows the last attempt as "{words:L}" with the mark "{mark:L}"')
def last_attempt(context, channel, account, words, mark):
    last = _line(context, channel, account)["lastAttempt"]
    assert last and last["words"] == words and last["mark"] == mark, last


# --- the blocked draft -------------------------------------------------------------------------------------------------------------------------------


@when('the checks on the draft of "{channel:L}" "{account:L}" fail because "{problem:L}"')
def checks_fail(context, channel, account, problem):
    row = [row for row in context.backend.rows("Delivery") if row["channel"] == channel and row["accountId"] == account][0]
    blocked_drafts.block_and_flag(context.deliveries, context.deliveries.get(row["id"]), problems=[problem], by="announce", now=context.now)


@when('a person answers the review flag of the Announcement "{key:L}"')
def flag_answered(context, key):
    from papyrus_content.review_requests import answer_review

    announcement = context.announcements.by_dedupe_key(key)
    answer_review(context.backend, blocked_drafts.flag_id(announcement["id"]), decision="approve", by="ellie")


@then("the answer shows the review flag once")
def flag_once(context):
    flags = [entry["reviewFlag"] for entry in _entries(context) if entry["reviewFlag"]]
    assert len(flags) == 1 and flags[0]["words"] == "Review requested: a draft was blocked" and flags[0]["mark"] == "flag", flags


@then("the answer shows no review flag")
def no_flag(context):
    assert not [entry for entry in _entries(context) if entry["reviewFlag"]], _entries(context)


@then("exactly {count:d} review request exists")
@then("exactly {count:d} review requests exist")
def requests_exist(context, count):
    assert len(context.backend.rows("ReviewRequest")) == count, context.backend.rows("ReviewRequest")


# --- the list ----------------------------------------------------------------------------------------------------------------------------------------


@then("the Announcements come in this order of release")
def list_order(context):
    found = [entry["releaseAt"] for entry in _entries(context)]
    assert found == [row["release"] for row in context.table], found


@then('the Announcement released "{release:L}" is about the Story titled "{title:L}"')
def list_titles(context, release, title):
    entry = [entry for entry in _entries(context) if entry["releaseAt"] == release][0]
    assert title in [story["title"] for story in entry["stories"]], entry["stories"]


@then("the pages hold these Announcements in turn")
def pages_hold(context):
    pages = [[entry["releaseAt"] for entry in page["announcements"]] for page in context.pages]
    expected = {}
    for row in context.table:
        expected.setdefault(int(row["page"]), []).append(row["release"])
    assert pages == [expected[number] for number in sorted(expected)], pages


@then("the last page has no next page")
def last_page(context):
    assert context.pages[-1]["next"] is None


@then("the question wrote nothing")
def nothing_written(context):
    assert context.backend.writes[context.writes_before:] == [], context.backend.writes[context.writes_before:]


# --- explain -----------------------------------------------------------------------------------------------------------------------------------------


def _channel(context, channel):
    found = [entry for entry in context.result["channels"] if entry["channel"] == channel]
    assert found, context.result
    return found[0]


@then("the explain command succeeded")
def command_succeeds(context):
    assert context.exit_code == 0 and context.envelope["ok"], context.envelope


@then('the explanation names the rule "{rule:L}" for the channel "{channel:L}"')
def explanation_rule(context, rule, channel):
    answer = _channel(context, channel)
    assert answer["rule"] == rule, answer


@then('the explanation for the channel "{channel:L}" says "{words:L}"')
def explanation_says(context, channel, words):
    answer = _channel(context, channel)
    assert words in answer["words"], answer


@then('the explanation says the channel "{channel:L}" was announced')
def explanation_announced(context, channel):
    answer = _channel(context, channel)
    assert answer["announced"] is True and answer["rule"] == "announced", answer


@then('the command is listed among the announcements commands as "{words:L}"')
def command_listed(context, words):
    tree = announcements_cli.route_tree()
    node = tree
    for word in words.split():
        assert word in node, (word, node)
        node = node[word]


@then('the default announcements commands include a handler for "{name:L}"')
def default_handler(context, name):
    assert name in announcements_cli.default_handlers(), sorted(announcements_cli.default_handlers())


@then('the door read the index "{index:L}" once')
def read_once(context, index):
    made = [read for read in context.backend.reads[context.reads_before:] if read[0] == index]
    assert len(made) == 1, context.backend.reads[context.reads_before:]


@then('the door never read the index "{index:L}"')
def never_read(context, index):
    assert not [read for read in context.backend.reads[context.reads_before:] if read[0] == index]


@then('the command failed with "{code:L}"')
def command_failed(context, code):
    assert context.exit_code != 0 and context.envelope["ok"] is False and context.envelope["error"]["code"] == code, context.envelope


# --- the console's door ------------------------------------------------------------------------------------------------------------------------------

EDITOR_IDENTITY = {"claims": {"name": "Edie Editor"}, "groups": ["editor"], "username": "edie"}
READER_IDENTITY = {"claims": {"name": "Rae Reader"}, "groups": [], "username": "rae"}


def _door(context, field, identity, op, payload):
    from papyrus_content.image_service import handle

    list_handlers._publication = lambda client: "publication"
    context.reads_before = len(context.backend.reads)
    context.writes_before = len(context.backend.writes)
    context.envelope = handle({"fieldName": field, "identity": identity, "arguments": {"op": op, "input": json.dumps(payload)}}, client_factory=lambda: context.backend,
                              files_factory=lambda client: context.files)
    context.result = context.envelope.get("result") or {}


@when('the console asks the announcements door for where the Story "{lineage:L}" was announced')
def console_asks_where(context, lineage):
    _door(context, "announcementsRead", EDITOR_IDENTITY, "announcements_where", {"story": lineage})
    assert context.envelope["ok"], context.envelope


@when("the console asks the announcements door for the list")
def console_asks_list(context):
    _door(context, "announcementsRead", EDITOR_IDENTITY, "announcements_recent", {})
    assert context.envelope["ok"], context.envelope


@when('a signed-in reader asks the announcements door for where the Story "{lineage:L}" was announced')
def reader_asks_where(context, lineage):
    _door(context, "announcementsRead", READER_IDENTITY, "announcements_where", {"story": lineage})


@when('the console asks the announcements door to "{op:L}"')
def console_asks_to_change(context, op):
    _door(context, "announcementsRead", EDITOR_IDENTITY, op, {})


@when('the console asks the image door for where the Story "{lineage:L}" was announced')
def image_door_asked(context, lineage):
    _door(context, "imageRead", EDITOR_IDENTITY, "announcements_where", {"story": lineage})


@then('the door refuses with "{code:L}"')
def door_refuses(context, code):
    assert context.envelope["ok"] is False and context.envelope["error"]["code"] == code, context.envelope


@then('the door refusal says "{text:L}"')
def door_refusal_says(context, text):
    assert text in context.envelope["error"]["message"], context.envelope


@then("the read path of the list loads without PyYAML")
def loads_without_yaml(context):
    import subprocess

    code = ("import sys; sys.modules['yaml'] = None\n"
            "import papyrus_content.image_service, papyrus_content.announcements.list_handlers as h, papyrus_content.announcements.lines\n"
            "assert set(h.DOOR_OPERATIONS) == {'announcements_where', 'announcements_recent'}\n")
    done = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, env={"PYTHONPATH": str(REPO_ROOT / "src"), "PATH": "/usr/bin"}, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-800:]


# --- the marks ---------------------------------------------------------------------------------------------------------------------------------------

MARKS_FILE = REPO_ROOT / "components" / "announcement-marks.tsx"


def _console_marks() -> dict[str, str]:
    import re

    source = MARKS_FILE.read_text(encoding="utf-8")
    table = source[source.index("export const MARK_ICONS"):source.index("};", source.index("export const MARK_ICONS"))]
    return {name.strip('"'): icon for name, icon in re.findall(r'^\s*("?[a-z0-9-]+"?):\s*([A-Za-z0-9]+),', table, re.MULTILINE)}


@then("the console's table of marks holds every mark the backend can say")
def console_has_marks(context):
    from papyrus_content.announcements import lines

    said = set(lines.MARKS)
    held = _console_marks()
    assert said <= set(held), sorted(said - set(held))
    wrong = {name: held[name] for name in said if held[name] != "".join(part.capitalize() for part in name.split("-"))}
    assert not wrong, f"a mark is drawn with an icon of another name: {wrong}"


@then("every icon in the console's table of marks is imported from Lucide")
def console_marks_are_lucide(context):
    import re

    source = MARKS_FILE.read_text(encoding="utf-8")
    imported = set(re.findall(r"\b([A-Z][A-Za-z0-9]+)\b", re.search(r"import \{([^}]*)\} from \"lucide-react\"", source, re.DOTALL).group(1)))
    assert set(_console_marks().values()) <= imported, set(_console_marks().values()) - imported
