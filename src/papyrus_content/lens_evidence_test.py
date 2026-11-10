"""The deterministic lens checks (features_backend/lens-check.feature has the narrative)."""

import json

from papyrus_content import audience_lenses as lenses
from papyrus_content import lens_evidence as evidence
from papyrus_content.projection.standard import blocks
from papyrus_content.projection.standard.config import standard_settings_from_mapping
from papyrus_content.projection.standard.environment import resolve_environment

ORIGIN = "https://example.test"


def row(body: str, front: str = "title: Board refuses\nsummary: The board refused it.\ndate: 2026-03-03\nauthor: Dana Reyes\n") -> dict:
    return {"id": "v1", "lineageId": "s1", "versionNumber": 1, "type": "article", "slug": "board", "section": None, "stage": "copywriting", "title": "Board refuses",
            "bodyMarkus": body, "metadata": json.dumps({"frontMatterYaml": front})}


def live_site() -> evidence.LensSite:
    standard = standard_settings_from_mapping({"site": {"name": "Example", "productionUrl": ORIGIN}, "seo": {"publisherName": "Example"}})
    return evidence.LensSite(standard, resolve_environment(standard, {"PAPYRUS_SITE_PUBLIC_URL": ORIGIN}))


def findings(body: str, site=None, front: str | None = None) -> dict:
    story = evidence.story_from_row(row(body) if front is None else row(body, front))
    return {found["check"]: found for found in evidence.run_checks(story, site)}


def test_every_check_marked_built_is_run_and_nothing_else_is():
    ran = set(findings("Words.\n", live_site()))
    built = {check.key for check in lenses.CHECK_BY_KEY.values() if check.built}
    assert ran == built


def test_every_check_not_run_has_a_reason_and_none_is_built():
    reasons = {row["check"] for row in evidence.not_run()}
    assert reasons == {check.key for check in lenses.CHECK_BY_KEY.values() if not check.built}
    assert all(row["reason"] for row in evidence.not_run())


def test_a_complete_story_on_a_live_site_has_no_problem_and_no_concern_about_the_site():
    found = findings("::image{src=\"/assets/own.jpg\" alt=\"A harbour\" credit=\"Image: A, CC0\"}\n\nThe board refused it.\n", live_site(),
                     "title: Board refuses\nsummary: The board refused it.\ndate: 2026-03-03\nauthor: Dana Reyes\nimage: /assets/own.jpg\nimageAlt: A harbour\n")
    assert [row["check"] for row in found.values() if row["state"] in ("concern", "problem")] == [], found


def test_three_errors_and_only_three_are_problems():
    body = "::image{src=\"https://p.example.test/x.jpg\"}\n\nWords.\n"
    problems = {key for key, found in findings(body).items() if found["state"] == "problem"}
    assert problems == {"P7", "P10", "C6"}


def test_a_check_that_could_not_run_carries_the_reason_and_no_severity_problem():
    found = findings("Words.\n")["S5"]
    assert found["state"] == "not_assessable" and "cannot read this site's settings" in found["message"]


COVER = "title: Board refuses\nsummary: The board refused it.\ndate: 2026-03-03\nauthor: Dana Reyes\nimage: /assets/h.jpg\ncoverImage:\n  source: wikimedia-commons\n  srcPath: assets/h.jpg\n"
SEEDED = "title: Board refuses\nsummary: The board refused it.\ndate: 2026-03-03\nauthor: Dana Reyes\nseededImage:\n  url: /assets/seed.jpg\n"


def credit_states(body: str, front: str | None = None) -> tuple[str, str]:
    found = findings(body, live_site(), front)
    return found["P10"]["state"], found["C6"]["state"]


def test_a_local_picture_with_no_credit_and_no_third_party_origin_is_ours():
    assert credit_states('::image{src="/assets/own.jpg" alt="A harbour"}\n\nWords.\n') == ("pass", "pass")


def test_a_local_picture_with_a_credit_passes():
    assert credit_states('::image{src="/assets/own.jpg" alt="A harbour" credit="Image: A, CC0"}\n\nWords.\n') == ("pass", "pass")


def test_a_credit_that_only_says_a_machine_made_it_still_passes():
    assert credit_states('::image{src="/assets/own.jpg" alt="A harbour" credit="Generated."}\n\nWords.\n') == ("pass", "pass")


def test_a_remote_picture_with_no_credit_fails():
    assert credit_states('::image{src="https://p.example.test/x.jpg" alt="A harbour"}\n\nWords.\n') == ("problem", "problem")


def test_a_stock_cover_picture_with_no_credit_fails():
    assert credit_states('::image{src="/assets/h.jpg" alt="A harbour"}\n\nWords.\n', COVER) == ("problem", "problem")


def test_a_reference_picture_with_no_credit_fails():
    assert credit_states('::image{src="/assets/seed.jpg" alt="A harbour"}\n\nWords.\n', SEEDED) == ("problem", "problem")


def test_counts_are_per_lens_step_and_mirrors_count_in_each():
    counts = evidence.summarize(list(findings("::image{src=\"a.png\"}\n", live_site()).values()))
    assert set(counts) == set(lenses.LENS_STEP_KEYS)
    assert counts["review_people"]["problem"] >= 1 and counts["review_social"].get("problem", 0) == 0


def test_twin_omissions_name_includes_and_raw_regions_with_their_lines():
    body = "Text.\n\n::include{kind=\"listing\" section=\"a\"}\n\n::raw\n<b>x</b>\n::endraw\n\nEnd.\n"
    assert [(row["kind"], row["line"], row["lines"]) for row in blocks.twin_omissions(body)] == [("include", 3, 1), ("raw", 5, 3)]
    assert blocks.twin_omissions("Text.\n\n::include{kind=\"block\" name=\"knowledge-x\"}\n") == []


def test_code_blocks_are_not_read_as_images_or_headings():
    body = "```\n::image{src=\"a.png\"}\n# not a heading\n```\n\nWords.\n"
    found = findings(body)
    assert found["P7"]["state"] == "not_applicable" and found["P6"]["state"] == "pass"


def test_a_story_whose_page_the_site_does_not_declare_still_gets_the_text_checks():
    standard = standard_settings_from_mapping({"site": {"name": "Example", "productionUrl": ORIGIN}, "urls": {"sections": {"news": {"base": "news"}}}})
    site = evidence.LensSite(standard, resolve_environment(standard, {}))
    odd = row("::image{src=\"a.png\"}\n")
    odd["section"] = "elsewhere"
    found = {each["check"]: each for each in evidence.run_checks(evidence.story_from_row(odd), site)}
    assert found["P7"]["state"] == "problem" and found["S5"]["state"] == "not_assessable" and "no page of its own" in found["S5"]["message"]
