Feature: A private review queue is filled from public sources without signing in to the app
  A collector gathers public discoveries into a private queue for a person to review later. It only collects: the batch carries no
  predictions and applies no labels, and several discoveries of one source stay together as revisions of that source. When a
  scheduled fetch fails, the last batch stays available and the failure is shown.

  Scenario: Resume a private morning review queue
    Given a private HN review queue and a feed with two discoveries of one source
    When the private collector repeats and one source title changes
    Then one review source retains all three discovery revisions
    And the private review batch contains no predictions or applied labels

  Scenario: Keep the last review batch when a scheduled fetch fails
    Given a private HN review queue and a feed with two discoveries of one source
    When the next due private collection fails
    Then the prior review source remains available with a visible collection failure
