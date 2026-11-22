Feature: A Reference's summary is saved once, with a record of who wrote it and from what
  The summary under a Reference is what an editor reads before deciding whether the source is worth a Story.
  It is kept with the Reference's other metadata, in one of five fixed lengths, together with whether a model
  or a person wrote it, when, and from which text. Saving the same summary again writes nothing, so a run
  that repeats costs nothing and changes nothing, and a summary with no words or an unknown length is refused.

  Background:
    Given a Reference titled "Teens and AI Companions" with no summary yet

  Scenario: A summary a model wrote is saved with the model, the length and the source text it read
    When the model "gpt-5.4-mini" summarises the Reference in 100 tokens as "Most U.S. teens have tried an AI companion."
    Then one write saves "Most U.S. teens have tried an AI companion." as the Reference's summary
    And the summary is recorded as written by a model, "gpt-5.4-mini", at the 100 token length
    And the summary records which source text it was written from

  Scenario: A summary a person wrote is recorded as theirs, and the publication's doctrine is not credited
    When a person writes the 100 token summary "Three in four teens have used one."
    Then one write saves "Three in four teens have used one." as the Reference's summary
    And the summary is recorded as written by a person
    And the summary records that the publication's doctrine was not used

  Scenario: Saving the summary the Reference already has writes nothing
    Given the Reference already has the summary "Most U.S. teens have tried an AI companion."
    When the model "gpt-5.4-mini" summarises the Reference in 100 tokens as "Most U.S. teens have tried an AI companion."
    Then no summary is written

  Scenario: Asking for a fresh summary writes it even when the words are the same
    Given the Reference already has the summary "Most U.S. teens have tried an AI companion."
    When the model "gpt-5.4-mini" is asked to summarise the Reference afresh in 100 tokens as "Most U.S. teens have tried an AI companion."
    Then one write saves "Most U.S. teens have tried an AI companion." as the Reference's summary

  Scenario Outline: A summary comes in one of five lengths and no other
    When a summary of length "<length>" is asked for
    Then the summary is <outcome>

    Examples:
      | length | outcome                                                                 |
      | 100    | accepted                                                                |
      | 200    | accepted                                                                |
      | 500    | accepted                                                                |
      | 1000   | accepted                                                                |
      | 1800   | accepted                                                                |
      | 150    | refused with "summary max tokens must be one of 100, 200, 500, 1000, or 1800" |
      | long   | refused with "summary max tokens must be one of 100, 200, 500, 1000, or 1800" |

  Scenario: A summary with no words is refused
    When the model "gpt-5.4-mini" summarises the Reference in 100 tokens as ""
    Then the summary is refused because it has no words
