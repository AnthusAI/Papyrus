Feature: The Translation lifecycle is data, and every language of a Story is in exactly one state
  A published Story in a site with other languages has one translation for each language, and each translation is in exactly one of six states: wanted, translating, held,
  ready, published or stale. The run keeps a finer state on its request; the lifecycle says what each of those means. A source edit makes the translation stale and wakes
  the translator for the changed blocks only, a block a person corrected is pinned and never overwritten (translation-correction.feature), and a hold raises one flag and
  blocks only its own translation: every other language, and every other Story, goes on. The states are read with one point read for each language, never by listing a table.

  Background:
    Given a published Story "slow-water" at version 2 that the site publishes in "es", "zh" and "fr"

  Scenario: A publish wants one translation for each language
    When the site wants a translation of "slow-water" in "es", "zh" and "fr"
    Then "slow-water" is "wanted" in "es", "zh" and "fr"

  Scenario: Every language has exactly one state
    Given the translation of "slow-water" into "es" is saved
    And the translation of "slow-water" into "zh" is held with the reason "a quotation needs a person"
    And no translation of "slow-water" into "fr" was ever requested
    When the states of "slow-water" are read
    Then the "es" translation is "ready"
    And the "zh" translation is "held"
    And the "zh" translation's reason is "a quotation needs a person"
    And the "fr" translation is "wanted"
    And each of the 3 languages has exactly one state

  Scenario Outline: Each state of the run means one lifecycle state
    Given the request for "es" is in the run state "<run>"
    When the states of "slow-water" are read
    Then the "es" translation is "<lifecycle>"

    Examples:
      | run       | lifecycle   |
      | wanted    | wanted      |
      | failed    | wanted      |
      | stopped   | wanted      |
      | started   | translating |
      | held      | held        |
      | waiting   | held        |
      | saved     | ready       |
      | unchanged | ready       |
      | published | published   |

  Scenario: A source edit makes the translation stale
    Given the translation of "slow-water" into "es" is published for source version 1
    When the states of "slow-water" are read
    Then the "es" translation is "stale"

  Scenario: A translation made for the current source is not stale
    Given the translation of "slow-water" into "es" is published for source version 2
    When the states of "slow-water" are read
    Then the "es" translation is "published"

  Scenario: A hold blocks one translation and the others proceed
    Given the translation of "slow-water" into "es" is held with the reason "a faithfulness error remains"
    And the translation of "slow-water" into "zh" is saved
    When the states of "slow-water" are read
    Then the "es" translation is "held"
    And the "zh" translation is "ready"
    And the lifecycle says a held translation raises one flag and blocks only that translation

  Scenario: The states are read by point reads only
    Given the translation of "slow-water" into "es" is saved
    When the states of "slow-water" are read
    Then the site made exactly 3 point reads and listed no table

  Scenario: A request in a state the lifecycle does not know is refused, not guessed
    Given the request for "es" is in the run state "paused"
    When the states of "slow-water" are read
    Then the read is refused saying "which the lifecycle does not know"
