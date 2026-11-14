from papyrus_content.concept_link_predicates import is_reference_concept_link


def test_reference_to_concept_mentions_and_related_to_count():
    assert is_reference_concept_link("mentions", "reference", "semanticNode")
    assert is_reference_concept_link("related_to", "reference", "semanticNode")


def test_reference_to_reference_related_to_does_not_count():
    assert not is_reference_concept_link("related_to", "reference", "reference")
    assert not is_reference_concept_link("cites", "reference", "semanticNode")
    assert not is_reference_concept_link("mentions", "item", "semanticNode")
