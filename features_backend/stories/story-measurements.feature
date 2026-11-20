Feature: Basic content measurements of a Story
  An editor, or an agent working for one, wants plain numbers about a story's text: how long it is, how it is built, how well it is
  sourced and how much a revision changed it. Humanus computes every number (Papyrus counts nothing itself); Papyrus hands it the text,
  the story's language and the headline, dek and blurb from the front matter, and shows the answer.

  "papyrus stories measure" works on a story that is already saved, or on a draft file before it is saved. "papyrus stories save-version"
  prints the same measurements of the version it saved, with how much that version changed from the one before it, and stores both with
  the new version record. The numbers are guidance and never a gate: no limit is applied and nothing is refused or blocked because of
  them. A story is measured in its own language: words in English and Spanish, characters in Simplified Chinese.

  Background:
    Given a story "hello" in English with a first version:
      """
      One two three four five six. Seven eight nine ten.

      A second paragraph cites [a source](https://example.com/source).
      """

  Scenario: A draft is measured before it is saved, against the story's current version
    Given a draft text to measure:
      """
      One two three four five six. Seven eight nine ten.

      A second paragraph cites [a source](https://example.com/source) and adds some words.

      ## A new section

      A third paragraph with no source at all.
      """
    When the draft is measured for the story
    Then the output shows the size in words
    And the output shows 1 section and 3 paragraphs
    And the output shows 1 link and no citations
    And the output shows the change against version 1
    And the measuring wrote nothing to the backend

  Scenario: A saved story is measured against the version before it
    Given the story has a second saved version with more words
    When the story is measured
    Then the output shows the change against version 1

  Scenario: The first version has no change to report
    When the story is measured
    Then the output shows no change

  Scenario: A draft with no story needs its language
    Given a draft text to measure:
      """
      Some words.
      """
    When the draft is measured without a story or a language
    Then the measurement is refused asking for --language

  Scenario: A draft with no story is measured in the language it is given
    Given a draft text to measure:
      """
      猫整天睡觉。它们在黄昏醒来。
      """
    When the draft is measured in "zh-Hans" without a story
    Then the output shows the size in characters

  Scenario: The headline, dek and blurb come from the front matter
    Given the draft has the front matter:
      """
      title: Cats sleep
      dek: Most of the day
      """
    And a draft text to measure:
      """
      Body words here.
      """
    When the draft is measured for the story
    Then the output shows the headline present, the dek present and the blurb absent

  Scenario: The measurements can be printed as JSON
    When the story is measured as JSON
    Then the JSON has the size, structure and sourcing measurements and the Humanus version

  Scenario: Saving a version prints the measurements and the change, and stores them with the version
    Given a draft text to measure:
      """
      One two three four five six. Seven eight nine ten.

      A second paragraph cites [a source](https://example.com/source) and adds some words.
      """
    When the draft is saved as the next version
    Then the version is saved with its measurements
    And the output shows the size in words
    And the output shows the change against version 1
    And the new version record stores the same measurements and the change against version 1

  Scenario: A dry run saves nothing and prints only what it always printed
    Given a draft text to measure:
      """
      Brand new words only.
      """
    When the draft is saved as the next version as a dry run
    Then the output is the dry-run line only
    And the measuring wrote nothing to the backend

  Scenario: A version saved without measurements does not keep the previous version's
    Given the story's current version carries measurements
    When another version is saved by a path that records none
    Then the new version record stores no measurements

  Scenario: Measurements never block a save
    Given a draft text to measure:
      """
      Tiny.
      """
    When the draft is saved as the next version
    Then the version is saved with its measurements
    And the output shows the size in words
