from papyrus_content.announcements.learned_examples import Example, Read, partitions


def test_a_draft_reads_the_publication_the_channel_and_the_kind():
    assert partitions("x", "story_published") == ["publication", "channel:x", "kind:x:story_published"]


def test_no_examples_add_nothing_to_the_prompt():
    assert Read().prompt == "" and Read().ids == []


def test_the_prompt_shows_each_draft_the_persons_version_and_the_reason():
    read = Read([Example("d1", "channel", "Draft.", "Better.", "Lead with the verb."), Example("d2", "kind", "Another.", "Other.")])
    assert read.ids == ["d1", "d2"]
    assert "Draft: Draft.\nPerson's version: Better.\nWhy: Lead with the verb." in read.prompt
    assert "Example 2 (applies to the kind)" in read.prompt and read.prompt.count("Why:") == 1
