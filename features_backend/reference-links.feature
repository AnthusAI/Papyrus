Feature: References are linked to each other and tagged with concepts, and a suggestion stays out of the graph until a person accepts it
  A Reference can relate to another Reference, and can be tagged with a concept, which is a node in the knowledge graph.
  Both are stored as one relation row. A link a person makes, or a rule derives, is current and the graph, the knowledge
  query and the wiki see it. A link a machine suggests is only a suggestion: it is stored with the state suggested, so
  every reader that asks for current links skips it, until a person accepts it. A person can also reject it, and the
  rejection is kept so the same suggestion is not offered again. Whoever decided, when, and why are recorded on the row.
  Writing the same link twice updates the one row. Tagging a Reference with a concept uses the "related to" relation;
  the "mentions" relation stays for concepts the enrichment found in the text.

  Background:
    Given the References "reference-a", "reference-b" and the concept "node-voice"

  Scenario: Linking two References twice leaves one link
    When an editor links "reference-a" and "reference-b" as related
    And an editor links "reference-b" and "reference-a" as related
    Then there is exactly one link between them
    And the link is current

  Scenario: A suggestion is invisible to current queries until a person accepts it
    When the newsroom suggests "reference-a" and "reference-b" as related with a similarity of 0.83
    Then the link is a suggestion
    And "reference-a" has no current links
    When an editor accepts the link with the reason "same-topic"
    Then "reference-a" has one current link
    And the link records who decided and the reason "same-topic"

  Scenario: A rejected suggestion is not offered again
    Given the newsroom suggested "reference-a" and "reference-b" as related
    When an editor rejects the link with the reason "off-topic"
    And the newsroom suggests "reference-a" and "reference-b" as related with a similarity of 0.9
    Then the link is rejected
    And "reference-a" has no current links

  Scenario: Tagging a Reference with a concept is a related-to link, not a mention
    When an editor tags "reference-a" with the concept "node-voice"
    Then the link goes from the Reference to the concept
    And the link uses the "related_to" relation

  Scenario: A human concept link counts in the concept report and on the concept page data
    Given the accepted Reference "reference-a" is linked to the concept "node-voice" only by an editor's related-to link
    And the accepted Reference "reference-b" is linked to "reference-a" by a related-to link
    When the concept report is built
    Then the concept "node-voice" has 1 distinct Reference in the report
    And the concept page data for "node-voice" lists "reference-a" as a linking Reference
    And the Reference-to-Reference link is not counted as a concept mention

  Scenario: Suggesting links for a Reference makes no embedding call
    Given the accepted References "reference-a", "reference-b" and "reference-c" are indexed
    When the newsroom suggests links for "reference-a"
    Then no embedding is requested
    And "reference-b" is suggested as related to "reference-a"

  Scenario: A rejected neighbour is never suggested again
    Given an editor rejected the link between "reference-a" and "reference-b"
    When the newsroom suggests links for "reference-a"
    Then "reference-b" is not suggested

  Scenario: A neighbour that is already linked is not suggested
    Given an editor linked "reference-a" and "reference-b" as related
    When the newsroom suggests links for "reference-a"
    Then "reference-b" is not suggested

  Scenario: How many neighbours are kept is decided by the largest drop in similarity
    Given the neighbours of a Reference have similarities 0.91, 0.88, 0.85, 0.52, 0.50, 0.49
    When the number of neighbours to keep is chosen
    Then the first 3 neighbours are kept
