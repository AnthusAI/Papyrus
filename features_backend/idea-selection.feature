Feature: The editor agent picks only the best ideas, under a rate limit
  Many ideas arrive every day, and a Story that gets picked runs through every stage to just before publishing. So the editor agent reads a section's ideas against
  the publication's and the section's mission and policy and against what has recently been published, and picks only the best. Picking none is a normal result. What
  "recent" means is a setting, because the right answer is something to experiment with. A rate limit caps new Stories in a section, by default one a day: it counts
  every Story that left the idea stage in the window, whoever moved it, and at the limit no model is called. A pick starts research and can be undone. A declined idea
  stays where it is with its reason. Nothing here calls a model or a network: the model is a stand-in.

  Background:
    Given a section with three ideas, the oldest of them rated by an editor

  Scenario: Most ideas are declined and the pick starts research
    Given the model picks the second idea and declines the others
    When the selection runs
    Then the model was asked to be picky, with room for 1 pick, and given every idea with its stars
    And the picked idea has a research assignment with the model's direction
    And the picked idea moved to the assignment stage as the editor agent
    And the picked idea records its reason, the pack and the settings
    And the declined ideas stay at the idea stage with their reasons
    And no idea is spiked

  Scenario: Picking none is a normal result
    Given the model declines every idea
    When the selection runs
    Then no research assignment is created
    And every idea records why it was declined

  Scenario: At the limit no model is called
    Given a Story in the section left the idea stage an hour ago
    When the selection runs
    Then no model was called
    And the outcome says the rate limit was reached

  Scenario: A person's pick counts toward the limit, and an old move does not
    Given a Story in the section left the idea stage three days ago
    And the model declines every idea
    When the selection runs
    Then the model was called
    When the selection runs with a window of 5 days and a limit of 1
    Then the outcome says the rate limit was reached

  Scenario: A higher limit leaves more room
    Given a Story in the section left the idea stage an hour ago
    And the model declines every idea
    When the selection runs with a window of 1 days and a limit of 3
    Then the model was asked to be picky, with room for 2 picks, and given every idea with its stars

  Scenario: The model cannot pick past the limit
    Given the model picks all three ideas
    When the selection runs
    Then only the first pick starts research
    And the other picks are reported as over the limit and record nothing

  Scenario: A pick with no direction is not started
    Given the model picks the first idea with no direction
    When the selection runs
    Then no research assignment is created
    And the idea records that it was not started

  Scenario: A dry run writes nothing
    Given the model picks the second idea and declines the others
    When the selection runs as a dry run
    Then the selection wrote nothing
    And the outcome still holds the decisions

  Scenario: A declined idea is not read again until it changes
    Given the model declines every idea
    When the selection runs
    And the selection runs a second time
    Then the second run had no idea to decide on
    When the selection runs again with again set
    Then the model was called again

  Scenario: Recent is passed to the pack as a setting
    Given the model declines every idea
    When the selection runs with recent meaning 5s in the section and 7d in the site
    Then the pack was asked for the 5 newest Stories in the section and 7 days in the site
    And each idea records those settings

  Scenario Outline: Recent is read from a short form
    Then "<text>" means <meaning>

    Examples:
      | text | meaning    |
      | 30d  | 30 days    |
      | 5s   | 5 stories  |

  Scenario: A recent setting that makes no sense is refused
    Then "soon" is refused as a recent setting

  Scenario: An unknown section is refused
    When the selection runs for a section that does not exist
    Then the selection is refused naming the section
