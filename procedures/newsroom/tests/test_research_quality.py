"""PPY-4b8e46 and PPY-0a5d52: contradicted versus not shown, names the editor excluded, clean titles and addresses, honest notes on References. No network."""
from papyrus_content import fact_check as fc
from papyrus_content import newsroom_context_pack as pack
from papyrus_content.assignments_workflow import research_packet_body
from papyrus_content.link_exploration import canonical_url as exploration_url
from papyrus_content.monitoring import canonical_url as monitoring_url
from papyrus_content.reference_identity import canonical_url_key, identity_keys
from papyrus_content.research_titles import canonical_record_url, clean_search_title, page_title, site_label, usable_title


def judged(answer, claim="Councilor Marlow spoke on Monday.", source="Councilor Marlow spoke on Tuesday."):
    return fc.check_claims([{"claim": claim, "sources": ["s"]}], {"s": source}, judge=lambda *args: answer)["claims"][0]


def test_the_judge_may_answer_contradicted_and_the_schema_allows_it():
    assert "contradicted" in fc.JUDGE_VERDICTS and "contradicted" in fc.JUDGE_SCHEMA["schema"]["properties"]["verdict"]["enum"]
    assert "Use this only when you can quote that passage" in fc.JUDGE_SYSTEM


def test_a_quoted_contradiction_is_contradicted_and_an_unquoted_one_is_only_not_shown():
    row = judged({"verdict": "contradicted", "quotes": ["Councilor Marlow spoke on Tuesday."]})
    assert (row["verdict"], row["reasons"]) == ("contradicted", ["judge_contradicted"])
    row = judged({"verdict": "contradicted", "quotes": []})
    assert row["verdict"] == "not_shown" and "quote_not_in_source" in row["reasons"]
    row = judged({"verdict": "contradicted", "quotes": ["Marlow never spoke."]})
    assert row["verdict"] == "not_shown"


def test_not_supported_and_silent_and_literal_failures_are_not_shown_not_contradicted():
    assert judged({"verdict": "not_supported", "quotes": []})["verdict"] == "not_shown"
    assert judged({"verdict": "source_silent", "quotes": []})["verdict"] == "not_shown"
    assert judged({"verdict": "supported", "quotes": ["Councilor Marlow spoke on Tuesday."]}, claim="Councilor Ada Marlow spoke on Tuesday.")["verdict"] == "not_shown"


def test_counts_separate_the_two_and_a_stored_rejected_counts_as_not_shown():
    counts = fc.counts_of([{"verdict": "contradicted", "sources": [], "sourceStrength": {"singleSource": False}}, {"verdict": "not_shown", "sources": [], "sourceStrength": {"singleSource": False}},
                           {"verdict": "rejected", "sources": [], "sourceStrength": {"singleSource": False}}])
    assert (counts["contradicted"], counts["not_shown"]) == (1, 2) and "rejected" not in counts
    assert [fc.held_group(v) for v in ("contradicted", "rejected", None, "not_shown", "needs_check", "unchecked")] == \
        ["contradicted", "not_shown", "not_shown", "not_shown", "needs_check", "unchecked"]


def test_the_packet_body_groups_held_claims_and_never_says_rejected():
    packet = {"summary": "S", "claims": [{"claim": "Fine.", "sources": [1]}], "unverifiedClaims": [
        {"claim": "A.", "sources": [1], "verdict": "contradicted", "reasons": ["judge_contradicted"]},
        {"claim": "B.", "sources": [1], "verdict": "rejected", "reasons": ["judge_not_supported"]},
        {"claim": "C.", "sources": [1], "verdict": "not_shown", "reasons": ["unmatched_terms: Ada"]}]}
    body = research_packet_body(packet)
    lines = body.splitlines()
    assert lines.index("Contradicted by its sources:") < lines.index("Not shown by the sources this run had (it may still be true):")
    assert body.count("Not shown by the sources this run had") == 1 and "Rejected" not in body and "(rejected" not in body
    assert lines.index("- B. [1] (judge_not_supported)") > lines.index("Not shown by the sources this run had (it may still be true):")


DIRECTION = ("Find work on confinement. Do not rely on Facebook's Bob and Alice or GibberLink, and treat the Gemini documents as leads. "
             "Look at NeurIPS papers, what was presented at ICML, the ICML workshop and Goguen and Meseguer, plus Rodney Reid's papers.")


def gap_names(direction):
    return [gap["name"] for gap in fc.direction_gaps(direction, [], ["nothing"])]


def test_names_after_an_exclusion_cue_labels_of_material_and_venues_are_not_subjects():
    names = gap_names(DIRECTION)
    assert names == ["Goguen", "Meseguer", "Rodney Reid"]


def test_a_cue_ends_at_the_clause_and_a_wanted_name_after_it_stays():
    assert gap_names("Ignore Bob; look into Alice.") == ["Alice"]
    assert gap_names("Do not rely on Bob, but do look into Alice.") == ["Alice"]
    assert gap_names("Do not use Bob, Carol, and Dan, and also look into Alice.") == ["Alice"]


def test_a_person_with_papers_stays_a_subject_and_a_leading_article_is_dropped():
    assert gap_names("Look at the Smith papers.") == ["Smith"]
    assert gap_names("Look into The Harbor Authority.") == ["Harbor Authority"]


def test_titles_lose_what_the_results_page_added():
    assert clean_search_title("[2204.06974] Planting Undetectable Backdoorsin Machine ...", "https://arxiv.org/abs/2204.06974") == "Planting Undetectable Backdoorsin Machine"
    assert clean_search_title("[arXiv:cs/0501001v2] Old Style", "https://arxiv.org/abs/cs/0501001") == "Old Style"
    assert clean_search_title("seL4 | Proceedings of the 2013 IEEE Symposium on Security and ...", "https://dl.acm.org/x") == "seL4"
    assert clean_search_title("Language-Based Information-Flow Security - CS@Cornell", "https://www.cs.cornell.edu/a.pdf") == "Language-Based Information-Flow Security"
    assert clean_search_title("Rice's theorem - Wikipedia", "https://en.wikipedia.org/wiki/Rice%27s_theorem") == "Rice's theorem"
    assert clean_search_title("A Survey - Part Two", "https://example.org/a") == "A Survey - Part Two"
    assert clean_search_title("Cornell", "https://www.cs.cornell.edu/") == "Cornell"
    assert site_label("https://bbc.co.uk/news") == "bbc" and site_label("https://link.springer.com/a") == "springer"


def test_a_page_title_is_used_unless_it_is_what_a_blocked_page_says():
    assert page_title("<title> A   Real\n Title </title>") == "A Real Title"
    assert page_title('<head><title>Site</title><meta name="citation_title" content="The Paper Title"></head>') == "The Paper Title"
    assert page_title("<title>Just a moment...</title>") is None
    assert usable_title("Microsoft Word - final.doc") is None and usable_title("survey.pdf") is None and usable_title("Home") is None


def test_arxiv_mirrors_become_the_arxiv_record_and_nothing_else_changes():
    for url in ("https://ar5iv.labs.arxiv.org/html/2204.06974v2", "https://ar5iv.org/abs/2204.06974", "https://arxiv.org/pdf/2204.06974v1.pdf",
                "https://export.arxiv.org/abs/2204.06974", "https://www.alphaxiv.org/abs/2204.06974"):
        assert canonical_record_url(url) == "https://arxiv.org/abs/2204.06974", url
    assert canonical_record_url("https://example.org/2204.06974") == "https://example.org/2204.06974"
    assert canonical_record_url("https://doi.org/10.1145/1") == "https://doi.org/10.1145/1"


def test_session_junk_is_dropped_by_both_normalisers_and_the_identity_key_agrees():
    junk = "https://link.springer.com/article/10.1007/s1?error=cookies_not_supported&code=1b2c3d4e"
    clean = "https://link.springer.com/article/10.1007/s1"
    assert exploration_url(junk) == monitoring_url(junk) == clean
    assert canonical_url_key(junk) == canonical_url_key(clean)
    assert identity_keys({"sourceUri": junk}) == identity_keys({"sourceUri": clean})
    assert exploration_url("https://x.org/p;jsessionid=AB12?q=1") == "https://x.org/p?q=1"
    assert exploration_url("https://x.org/p?PHPSESSID=abc&q=1") == "https://x.org/p?q=1"
    assert exploration_url("https://x.org/p?error=none&code=7") == "https://x.org/p?error=none&code=7"


def test_the_note_on_a_reference_is_labelled_for_what_it_is():
    found = "Found by perplexity (undecidability proof): Rice's theorem"
    assert pack.reason_line({"curationStatus": "pending", "curationStatusReason": found}) == ("How it was found", found)
    assert pack.reason_line({"curationStatus": "accepted", "curationStatusReason": found, "curationActorKind": "human",
                             "metadata": '{"ingestion_rationale": "%s"}' % found}) == ("How it was found", found)
    assert pack.reason_line({"curationStatus": "rejected", "curationStatusReason": "Not relevant", "curationActorKind": "cyclotron"}) == ("Rejected because", "Not relevant")
    assert pack.reason_line({"curationStatus": "accepted", "curationStatusReason": "Key ruling"}) == ("Accepted because", "Key ruling")
    assert pack.reason_line({"curationStatus": "archived", "curationStatusReason": "Old"}) == ("Archived because", "Old")
    assert pack.reason_line({"curationStatus": "pending", "curationStatusReason": "Hmm", "curationActorKind": "human"}) == ("Note from the last decision", "Hmm")
    assert pack.reason_line({"curationStatus": "accepted", "curationStatusReason": "  "}) is None
    assert pack.reason_phrase(("Accepted because", "x")) == "accepted because x" and pack.reason_phrase(("How it was found", "x")) == "how it was found: x"
