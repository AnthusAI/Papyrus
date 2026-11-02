Feature: A pack idea joins its References and never writes from titles
  A context pack is a theme the newsroom's own activity surfaced: several accepted References that belong together. An idea written from a pack is
  worth filing only when it connects them, and it can connect only what it has read. So a pack idea needs at least one sentence that cites two References
  together (otherwise it is two summaries side by side), and it may cite only References that have a summary beyond their title. A pack whose
  References are known only by their titles is skipped before the model is asked and is offered again on the next run, when a summary may exist. A Reference's
  summary is the first that exists of: the summary Message linked to it, the metadata attachment's summary, the curation attachment's summary, and the
  preview attachment's description when it is more than the title.

  Scenario: A pack whose References have only titles is skipped and the model is not asked
    Given a pack of four accepted References of which one has a summary
    When the pack is written under the minimum standard "more-than-summary"
    Then the pack's model is asked 0 times
    And the pack is skipped as "nothing_to_add"

  Scenario: A pack idea with no sentence citing two References together is dropped
    Given a pack of four accepted References that all have summaries
    And the model writes an idea whose sentences each cite a single Reference
    When the pack is written under the minimum standard "more-than-summary"
    Then the pack files no idea
    And the idea was dropped because it has "no_joint_sentence"

  Scenario: A pack idea with a sentence citing two References together is filed
    Given a pack of four accepted References that all have summaries
    And the model writes an idea with a sentence citing two References together
    When the pack is written under the minimum standard "more-than-summary"
    Then the pack files 1 idea

  Scenario: A pack idea may not cite a Reference that has only a title
    Given a pack of four accepted References of which two have summaries
    And the model writes an idea with a sentence citing a Reference without a summary
    When the pack is written under the minimum standard "more-than-summary"
    Then the pack files no idea
    And the idea was dropped because it has "cites_reference_without_summary"

  Scenario: A Reference's summary comes from the first source that has one
    Given a Reference whose preview attachment describes it and whose curation attachment summarises it
    Then its summary is the curation attachment's
    Given a Reference whose preview attachment only repeats its title
    Then it has no summary
