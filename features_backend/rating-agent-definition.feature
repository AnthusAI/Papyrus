Feature: The rating agent is the first core agent definition
  The engine ships one definition for the standing responsibility "rate": the agent that gives unrated published Stories and accepted References a
  rating. It is the agent that first runs on Machines on Machines, at the rung observe. Its definition fills all 11 lines of the template, wakes by a
  daily schedule, runs one at a time for the agent, is safe to repeat and is paid, with the bulk model tier (ratings are bulk curation). It names each
  operation it uses at exactly the lowest rung the operation table gives that operation. It never assigns five stars: three stars is the default,
  four is for a clearly better item, and a five is only ever a candidate that a person decides. It never publishes. The definition names no rung for
  the agent: how far it goes is the site's agent policy. This feature specifies the definition; the rating procedure itself has its own feature.

  Scenario: The engine ships the rating agent definition
    When the engine's core definitions are validated
    Then the set is accepted
    And the core set holds the definition "rate" for the responsibility "rate"

  Scenario: The rating agent runs on the bulk tier, once a day, one at a time
    When the engine's core definitions are validated
    Then the definition "rate" has the tier "bulk"
    And the definition "rate" wakes by a daily schedule and by no change
    And the definition "rate" runs one at a time by "agent"
    And the definition "rate" is paid and safe to repeat

  Scenario: Each operation is named at the lowest rung of the operation table
    When the engine's core definitions are validated
    Then every operation of the definition "rate" is named at the lowest rung the operation table allows

  Scenario: The rating agent never assigns five stars and never publishes
    When the engine's core definitions are validated
    Then the definition "rate" must never "Assign five stars"
    And the definition "rate" must never "Publish, unpublish, accept or reject"
    And the definition "rate" must never "Change or replace a rating a person gave"

  Scenario: The definition names no rung for the agent
    When the engine's core definitions are validated
    Then the definition "rate" names no rung, pause, budget or model

  Scenario: papyrus agents validate accepts the engine's core definitions
    When papyrus agents validate is run on the engine's core definitions with the network closed
    Then the command exits with status 0
    And the answer lists "rate" among the definitions using the operation "guidelines_resolve"

  Scenario: A site may add a must-never rule to the rating agent and cannot remove one
    Given a site definitions folder that extends the core definition "rate" with the must-never rule "Rate an item from a source the site has rejected"
    When the engine's core definitions are validated with that site folder
    Then the set is accepted
    And the effective definition "rate" keeps every must-never rule of the shipped definition
