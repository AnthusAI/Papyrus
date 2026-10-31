from papyrus_content.cross_story_boilerplate import ShingleIndex, Story, comparable_words, cross_story_findings, latest_stories

CLOSING = "We run this for clients at scale and we keep the source open so every client owns the whole thing"


def index(*bodies):
    return ShingleIndex([Story(f"s{n}", f"slug-{n}", body) for n, body in enumerate(bodies)])


def test_shared_closing_is_one_finding_naming_the_other_story():
    found = cross_story_findings(f"Intro here.\n\n{CLOSING}.", "mine", index(f"Other intro.\n\n{CLOSING}."))
    assert len(found) == 1
    assert found[0]["policyId"] == "cross-story-boilerplate" and found[0]["severity"] == "warn"
    assert "slug-0" in found[0]["message"] and found[0]["excerpt"] == CLOSING


def test_own_lineage_is_never_compared():
    assert cross_story_findings(CLOSING, "s0", index(CLOSING)) == []


def test_shared_run_is_a_union_of_stories_over_overlapping_windows():
    found = cross_story_findings(f"{CLOSING}.", "mine", index(CLOSING, CLOSING + " plus more"))
    assert len(found) == 1 and "slug-0" in found[0]["message"] and "slug-1" in found[0]["message"]


def test_excluded_spans_do_not_count():
    body = f"---\ntitle: {CLOSING}\n---\n\n```\n{CLOSING}\n```\n\n> {CLOSING}\n\n\"{CLOSING}\"\n\n[link](https://example.com/{CLOSING.replace(' ', '-')})"
    assert cross_story_findings(body, "mine", index(CLOSING)) == []
    assert comparable_words(body)[:2] == [("link", body.index("[link]") + 1, body.index("[link]") + 5, comparable_words(body)[0][3])]


def test_short_runs_and_runs_split_by_a_break_are_ignored():
    assert cross_story_findings("We run this for clients at scale.", "mine", index("We run this for clients at scale.")) == []
    split = " ".join(CLOSING.split()[:11]) + ' "quoted words" ' + " ".join(CLOSING.split()[11:])
    assert cross_story_findings(split, "mine", index(CLOSING)) == []


def test_latest_stories_takes_the_highest_current_or_draft_version_per_lineage():
    rows = [
        {"id": "a-v1", "lineageId": "a", "versionNumber": 1, "versionState": "superseded", "slug": "a", "bodyMarkus": "old"},
        {"id": "a-v2", "lineageId": "a", "versionNumber": 2, "versionState": "current", "slug": "a", "bodyMarkus": "cur"},
        {"id": "a-v3", "lineageId": "a", "versionNumber": 3, "versionState": "draft", "slug": "a", "bodyMarkus": "draft"},
    ]
    assert [(s.lineage_id, s.body) for s in latest_stories(rows)] == [("a", "draft")]
