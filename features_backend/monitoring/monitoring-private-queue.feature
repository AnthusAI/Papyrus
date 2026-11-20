Feature: Public collection supplies a private review batch without app authentication
  Collection is independent of classification and never applies human feedback.

  Scenario: Resume a private morning review queue
    Given a private HN review queue and a feed with two discoveries of one source
    When the private collector repeats and one source title changes
    Then one review source retains all three discovery revisions
    And the private review batch contains no predictions or applied labels

  Scenario: Keep the last review batch when a scheduled fetch fails
    Given a private HN review queue and a feed with two discoveries of one source
    When the next due private collection fails
    Then the prior review source remains available with a visible collection failure
