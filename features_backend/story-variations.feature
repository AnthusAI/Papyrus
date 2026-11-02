Feature: A Story can hold several variations for an editor to choose from
  A new item could connect to what the newsroom knows in more than one way: to another Reference, to another Story, to a Concept. Each of those is a variation:
  its own point, wording and connections, side by side with the others. A variation is not a version. Versions are a Story's one line of edits, and variations
  are alternatives that exist at the same time.

  An editor accepts one or rejects any of them, with a reason, and nothing is deleted, so what was turned down and why stays readable. An editor can also ask, in
  the Story's conversation, for a new variation that combines parts of others, and that variation records the Message that asked and the variations it came from.

  Background:
    Given a Story at the idea stage

  Scenario: A variation records its point and what it connects to
    When a run offers a variation with the point "Two accounts disagree on the cause" connecting to a Reference and a Concept
    Then the Story has 1 variation
    And variation 1 is on offer
    And variation 1 connects to a "reference" and a "concept"

  Scenario: A Story's variations stay in the order they were offered
    When a run offers a variation with the point "First" connecting to a Reference and a Concept
    And a run offers a variation with the point "Second" connecting to another Story
    Then the Story has 2 variations
    And variation 2 has the point "Second"
    And variation 2 connects to a "story"

  Scenario: The same variation offered twice is kept once
    When a run offers a variation with the point "First" connecting to a Reference and a Concept
    And a run offers a variation with the point "First" connecting to a Reference and a Concept
    Then the Story has 1 variation

  Scenario: A variation with no point is refused
    When a run offers a variation with no point
    Then the variation is refused because it must make a point
    And the Story has 0 variations

  Scenario: A generated variation must name what it connects to
    When a run offers a variation with the point "First" connecting to nothing
    Then the variation is refused because it must name what it connects to
    And the Story has 0 variations

  Scenario: A person can write a variation that connects to nothing yet
    When an editor writes a variation with the point "My own angle"
    Then the Story has 1 variation
    And variation 1 came from a "person"

  Scenario: A variation asked for in the conversation records what it came from
    Given a run offered variations "First" and "Second"
    When a variation combining them is requested by a Message
    Then variation 3 came from a "requested"
    And variation 3 is based on variations 1 and 2
    And variation 3 records the Message that asked

  Scenario: A requested variation must name the Message that asked
    Given a run offered variations "First" and "Second"
    When a variation combining them is requested with no Message
    Then the variation is refused because it must name the Message
    And the Story has 2 variations

  Scenario: A variation cannot be based on another Story's variation
    Given a run offered variations "First" and "Second"
    When a variation is requested based on a variation this Story does not have
    Then the variation is refused because this Story does not have it
    And the Story has 2 variations

  Scenario: Accepting a variation records who chose it
    Given a run offered variations "First" and "Second"
    When an editor accepts variation 1 saying "This is the real disagreement"
    Then variation 1 is accepted
    And variation 1 records the editor and the reason "This is the real disagreement"
    And variation 2 is on offer

  Scenario: A Story has one accepted variation at a time
    Given a run offered variations "First" and "Second"
    When an editor accepts variation 1 saying "For now"
    And an editor accepts variation 2 saying "Better"
    Then variation 2 is accepted
    And variation 1 is on offer

  Scenario: A rejected variation stays on record with its reason
    Given a run offered variations "First" and "Second"
    When an editor rejects variation 2 saying "Only restates the source"
    Then variation 2 is rejected
    And variation 2 records the editor and the reason "Only restates the source"
    And the Story has 2 variations

  Scenario: An editor can change their mind about a rejected variation
    Given a run offered variations "First" and "Second"
    When an editor rejects variation 2 saying "Not yet"
    And an editor accepts variation 2 saying "Now it fits"
    Then variation 2 is accepted
