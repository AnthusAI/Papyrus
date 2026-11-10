"""The duplicate rules (``data/entity-duplicate-rules.yml``) against the pairs the live Machines on Machines map showed, and the pairs that must stay apart."""

from __future__ import annotations

import pytest

from .entity_duplicates import (
    DuplicateFinder,
    RulesError,
    default_rules,
    duplicate_proposal,
    find_duplicate,
    find_duplicate_pairs,
    parse_rules,
    proposal_id,
)
from .keys import entity_key


def node(kind: str, name: str, aliases=(), status="accepted", state="current") -> dict:
    key = entity_key(kind, name)
    return {"id": f"semantic-node-{key}-v1", "lineageId": f"semantic-node-{key}", "nodeKey": key, "nodeKind": kind, "displayName": name, "aliases": list(aliases), "status": status, "versionState": state}


# (kind, the name already on the map, the name the extractor brings, the rule that must fire, what it says to do)
MUST_BE_CAUGHT = [
    ("organization", "The National Transportation Safety Board", "The NTSB", "acronym", "propose"),
    ("organization", "The NTSB", "The National Transportation Safety Board", "acronym", "propose"),
    ("software", "The Model Context Protocol", "MCP", "acronym", "propose"),
    ("organization", "Redwood Research", "Redwood", "containment", "propose"),
    ("organization", "Redwood", "Redwood Research", "containment", "propose"),
    ("organization", "The UK AI Security Institute", "And the UK AI Security Institute", "leading_word", "resolve"),
    ("organization", "And the UK AI Security Institute", "The UK AI Security Institute", "leading_word", "resolve"),
    ("organization", "UK AI Security Institute", "And the UK AI Security Institute", "leading_word", "resolve"),
    ("organization", "Mistral AI", "mistral-ai", "same_name", "resolve"),
    *[
        ("person", full, surname, "surname", "propose")
        for full, surname in [
            ("Dario Amodei", "Amodei"), ("Elon Musk", "Musk"), ("Nicholas Carlini", "Carlini"), ("Alan Turing", "Turing"), ("Arthur Samuel", "Samuel"),
            ("Daniel Stenberg", "Stenberg"), ("Norbert Wiener", "Wiener"), ("Simone Weil", "Weil"), ("Arturo Rosenblueth", "Rosenblueth"),
            ("Harold Cohen", "Cohen"), ("Refik Anadol", "Anadol"), ("Robert Dillon", "Dillon"),
        ]
    ],
    ("person", "Musk", "Elon Musk", "surname", "propose"),
]

MUST_STAY_APART = [
    ("concept", "Reinforcement learning", "RLHF"),
    ("model", "AlphaGo", "AlphaGo Zero"),
    ("model", "GPT-Rosalind", "GPT-Rosalind-5.5"),
    ("organization", "Google", "Mistral AI"),
    ("person", "John Smith", "Smith"),  # a second Smith would make the surname ambiguous (see below)
]


@pytest.mark.parametrize("kind, existing, candidate, rule, action", MUST_BE_CAUGHT)
def test_the_pairs_the_live_map_showed_are_caught_by_the_rule_that_names_them(kind, existing, candidate, rule, action):
    hit = find_duplicate(kind, candidate, [node(kind, existing)])
    assert hit is not None, f"{candidate!r} should duplicate {existing!r}"
    assert (hit.rule, hit.action, hit.node["displayName"]) == (rule, action, existing)


@pytest.mark.parametrize("kind, existing, candidate", MUST_STAY_APART[:4])
def test_distinct_things_are_not_flagged(kind, existing, candidate):
    assert find_duplicate(kind, candidate, [node(kind, existing)]) is None
    assert find_duplicate(kind, existing, [node(kind, candidate)]) is None


def test_a_surname_is_a_duplicate_only_when_exactly_one_full_name_person_has_it():
    people = [node("person", "John Smith"), node("person", "Jane Smith")]
    assert find_duplicate("person", "Smith", people) is None
    assert find_duplicate("person", "Smith", people[:1]).node["displayName"] == "John Smith"
    # The other direction: a full name beside a bare surname, when the surname is shared the bare one is ambiguous, not a duplicate.
    assert find_duplicate("person", "John Smith", [node("person", "Smith")]).node["displayName"] == "Smith"
    assert find_duplicate("person", "John Smith", [node("person", "Smith"), node("person", "Jane Smith")]) is None


def test_the_surname_and_containment_rules_belong_to_their_kinds():
    assert find_duplicate("software", "Musk", [node("software", "Elon Musk")]) is None  # the surname rule is for people
    assert find_duplicate("organization", "Musk", [node("organization", "Elon Musk")]).rule == "containment"  # an organization is read by the organization rule
    assert find_duplicate("person", "Redwood", [node("person", "Redwood Research")]) is None
    assert find_duplicate("software", "Redwood", [node("software", "Redwood Research")]) is None


def test_the_same_name_in_another_kind_is_an_ambiguity_not_a_duplicate():
    assert find_duplicate("organization", "Mistral", [node("model", "Mistral")]) is None
    assert find_duplicate("model", "The NTSB", [node("organization", "NTSB")]) is None


def test_an_alias_of_an_entity_counts_as_one_of_its_names():
    existing = node("organization", "NTSB", aliases=["National Transportation Safety Board"])
    assert find_duplicate("organization", "The National Transportation Safety Board", [existing]).rule == "leading_word"


def test_initials_skip_connectors_and_need_two_words():
    cdt = node("organization", "Center for Democracy and Technology")
    assert find_duplicate("organization", "CDT", [cdt]).rule == "acronym"
    assert find_duplicate("organization", "CD", [cdt]) is None
    assert find_duplicate("organization", "Ab", [node("organization", "Alpha")]) is None  # one word has no initials
    assert find_duplicate("organization", "mcp", [node("organization", "Model Context Protocol")]) is None  # an acronym is upper case


def test_only_current_accepted_entities_are_targets():
    for state in ({"status": "generated"}, {"status": "rejected"}, {"status": "superseded"}, {"state": "superseded"}):
        assert find_duplicate("organization", "Redwood", [node("organization", "Redwood Research", **state)]) is None


def test_a_candidate_is_never_its_own_duplicate():
    existing = node("organization", "Redwood Research")
    assert find_duplicate("organization", "Redwood Research", [existing], own_lineage=existing["lineageId"]) is None


def test_the_first_rule_in_the_file_decides_and_the_first_key_breaks_a_tie():
    nodes = [node("organization", "Redwood Research Labs"), node("organization", "Redwood Research")]
    assert find_duplicate("organization", "Redwood", nodes).node["displayName"] == "Redwood Research"
    both = [node("organization", "The Redwood"), node("organization", "Redwood Research")]
    assert find_duplicate("organization", "Redwood", both).rule == "leading_word"


def test_a_finder_takes_an_entity_accepted_later():
    finder = DuplicateFinder([])
    assert finder.find("person", "Musk") is None
    finder.add(node("person", "Elon Musk"))
    assert finder.find("person", "Musk").node["displayName"] == "Elon Musk"
    finder.add(node("person", "Maye Musk"))  # now the surname is shared
    assert finder.find("person", "Musk") is None


def test_the_pair_report_lists_each_pair_once_with_the_larger_key_as_the_duplicate():
    nodes = [node(kind, existing) for kind, existing, *_ in MUST_BE_CAUGHT[:2]] + [node("person", "Elon Musk"), node("person", "Musk"), node("model", "AlphaGo"), node("model", "AlphaGo Zero")]
    pairs = {(row["displayName"], hit.node["displayName"], hit.rule) for hit, row in find_duplicate_pairs(nodes)}
    assert pairs == {("The NTSB", "The National Transportation Safety Board", "acronym"), ("Musk", "Elon Musk", "surname")}


def test_the_rules_file_is_the_data_the_check_reads():
    rules = default_rules()
    assert [rule.id for rule in rules.rules] == ["same_name", "leading_word", "acronym", "surname", "containment"]
    assert {rule.id: rule.action for rule in rules.rules} == {"same_name": "resolve", "leading_word": "resolve", "acronym": "propose", "surname": "propose", "containment": "propose"}
    assert rules.leading_words == {"the", "a", "an", "and"}
    # A different list changes the verdict without touching code.
    only_containment = parse_rules({"leading_words": [], "rules": [{"id": "c", "check": "containment", "action": "resolve"}]})
    hit = find_duplicate("model", "AlphaGo", [node("model", "AlphaGo Zero")], rules=only_containment)
    assert (hit.rule, hit.action) == ("c", "resolve")


@pytest.mark.parametrize("body", [None, {}, {"rules": [{"id": "x", "check": "no-such-check", "action": "resolve"}]}, {"rules": [{"id": "x", "check": "acronym", "action": "merge"}]}, {"rules": [{"check": "acronym", "action": "propose"}]}])
def test_a_malformed_rules_file_is_an_error_not_a_gap(body):
    with pytest.raises(RulesError):
        parse_rules(body)


def test_a_proposal_is_one_row_per_candidate_and_entity_and_says_what_to_run():
    existing = node("person", "Elon Musk")
    hit = find_duplicate("person", "Musk", [existing])
    alias = duplicate_proposal(hit, "person", None, corpus_id="corpus-1", import_run_id="run-1", now="2026-11-10T00:00:00Z")
    assert (alias["proposalKind"], alias["steeringDomain"], alias["status"], alias["graphEntityId"]) == ("entity-alias-edit", "graph", "proposed", "person--elon-musk")
    assert "knowledge entities alias --key person--elon-musk" in alias["description"]
    generated = node("person", "Musk", status="generated")
    merge = duplicate_proposal(hit, "person", generated, corpus_id="corpus-1", import_run_id="run-1", now="2026-11-10T00:00:00Z")
    assert merge["proposalKind"] == "merge-graph-entity" and "knowledge entities merge --from person--musk --into person--elon-musk" in merge["description"]
    assert alias["id"] == merge["id"] == proposal_id("person", "Musk", existing)
    again = duplicate_proposal(find_duplicate("person", " musk ", [existing]), "person", None, corpus_id="corpus-1", import_run_id="run-2", now="2026-11-11T00:00:00Z")
    assert again["id"] == alias["id"]
