"""papyrus_content.fact_check: the literal check's matching rules, source strength and the replay command, on invented text only. No network."""
import json
from unittest import mock

from papyrus_content import fact_check as fc
from papyrus_content import multi_search_research as ms


def terms(claim, *texts, hosts=()):
    return [row["term"] for row in fc.literal_check(claim, list(texts), list(hosts))]


def test_every_word_of_a_name_must_be_found():
    assert terms("Rodney Reid was jailed.", "Reid was jailed.") == ["Rodney"]
    assert terms("Reid was jailed.", "Rodney Reid was jailed.") == []


def test_diacritics_case_and_curly_quotes_do_not_matter():
    assert terms("José Núñez left.", "JOSE NUNEZ left") == []
    assert terms("The man’s name was Orrin.", "the man's name was orrin") == []


def test_numbers_match_across_formats_and_spelled_out_forms():
    assert terms("It cost $200,000, up 12%, in 2024, for 15 homes.", "200000 dollars, 12 percent, 2024, fifteen homes") == []
    assert terms("Twenty-three people came.", "23 people came") == []
    assert terms("It cost 3.50 dollars.", "3.5 dollars") == []
    assert terms("It cost 300 dollars.", "30 dollars, 3000 later") == ["300"]


def test_a_name_can_be_a_short_form_or_the_cited_sites_host():
    assert terms("The Revenue Accountability Office said so.", "RAO said so") == []
    assert terms("A New York judge ruled.", "Case 12 NY Slip Op") == []
    assert terms("Washington law applies.", "RCW 1.2.3", hosts=["app.leg.wa.gov"]) == []
    assert terms("Orlando policy applies.", "A policy.", hosts=["www.orlando.gov"]) == []
    assert terms("Silverlake Tribune reported it.", "It was reported.", hosts=["silverlaketribune.com"]) == []
    assert terms("Ohio policy applies.", "A policy.", hosts=["www.orlando.gov"]) == ["Ohio"]


def test_months_and_generic_sentence_openers_are_not_names_but_a_name_that_opens_a_sentence_is():
    assert terms("The plan passed in March.", "plan passed") == []
    assert terms("Marlow resigned.", "Councilor resigned.") == ["Marlow"]


def test_a_quotation_is_checked_whole():
    assert terms('She said "a plain mistake" today.', "she said “a plain mistake” today") == []
    assert terms('She said "a grave mistake" today.', "she said a plain mistake") == ["a grave mistake"]


def test_registered_domains_and_strength():
    assert fc.registered_domain("https://news.example.co.uk/a") == "example.co.uk"
    assert fc.registered_domain("https://www.example.com/a") == "example.com"
    assert fc.source_strength(["a", "b"], {"a": "https://x.example.com/1", "b": "https://www.example.com/2"}) == {"domains": 1, "singleSource": True}
    assert fc.source_strength(["a", "b"], {"a": "https://x.example.com/1", "b": "https://other.example.org/2"}) == {"domains": 2, "singleSource": False}


def test_a_judge_answer_that_is_not_a_verdict_leaves_the_claim_unchecked():
    report = fc.check_claims([{"claim": "A plain claim.", "sources": ["s"]}], {"s": "A plain claim."}, judge=lambda claim, cited, info=None: {"nonsense": True})
    assert report["claims"][0]["verdict"] == "unchecked" and report["claims"][0]["reasons"][0].startswith("judge_failed")


def test_supported_without_a_quote_is_demoted():
    judge = lambda claim, cited, info=None: {"verdict": "supported", "quotes": [], "explanation": "", "attribution_lost": False}
    report = fc.check_claims([{"claim": "A plain claim.", "sources": ["s"]}], {"s": "A plain claim."}, judge=judge)
    assert report["claims"][0]["verdict"] == "rejected" and "quote_not_in_source" in report["claims"][0]["reasons"]


def test_the_llm_judge_sends_only_the_claim_and_the_cited_texts_with_a_strict_schema():
    seen = []

    def llm(system, user, schema):
        seen.append((system, json.loads(user), schema))
        return {"verdict": "source_silent", "quotes": [], "explanation": "", "attribution_lost": False}

    fc.llm_judge(llm)("A claim.", {"s1": "Some text."})
    system, given, schema = seen[0]
    assert given == {"statement": "A claim.", "sources": [{"id": "s1", "title": "", "host": "", "text": "Some text."}]}
    assert schema["strict"] and schema["schema"]["properties"]["verdict"]["enum"] == list(fc.JUDGE_VERDICTS) and "written" not in given


def test_the_replay_command_reads_a_packet_and_writes_nothing(capsys):
    research = {"claims": [{"claim": "Orrin Vale spoke.", "sources": [1]}], "multiSearch": {"sourceProviders": [{"index": 1, "url": "https://a.example.com/x"}]},
                "proposedReferences": [{"url": "https://a.example.com/x", "title": "Vale", "snippets": ["Vale spoke."]}]}
    client = mock.Mock()
    client.get_record.return_value = {"id": "message-1"}
    with mock.patch("papyrus_content.graphql_authoring.create_authoring_client", return_value=(client, None)), \
         mock.patch.object(ms, "load_message_metadata_payload", return_value={"research": json.dumps(research)}):
        ms.fact_check_command(["--message", "message-1", "--judge", "false", "--format", "json"])
    printed = json.loads(capsys.readouterr().out)
    assert printed["claims"][0]["literal"]["unmatched"] == [{"term": "Orrin", "kind": "name"}] and printed["judge"] is False
    assert not client.method_calls or all(call[0] == "get_record" for call in client.method_calls)


def test_quote_pieces_split_at_ellipses():
    assert fc.quote_pieces("alpha ... beta\u2026gamma") == ["alpha", "beta", "gamma"]

