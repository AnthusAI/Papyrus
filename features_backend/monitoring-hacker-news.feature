Feature: A recurring Hacker News Monitor registers publication-scoped discoveries
  A small worker uses the existing Reference intake, preserving source provenance
  and checkpoints. Collection never curates or trains a classifier.

  Scenario: Repeat a real-shaped source batch without duplicate registration
    Given a configured Hacker News Monitor and a two-item feed
    When the Monitor collects the feed twice
    Then two persisted Reference receipts have source and publication provenance
    And the second collection does not register the unchanged items again

  Scenario: Retry an interrupted intake without losing prior work
    Given a configured Hacker News Monitor and a two-item feed
    And the second item fails intake once
    When the Monitor collects the feed twice
    Then the first item is not registered again
    And the second item has a successful persisted receipt after retry

  Scenario: Observe a source revision without changing a human decision
    Given a configured Hacker News Monitor and a two-item feed
    When a previously collected source title changes
    Then a new discovery revision is recorded for the same canonical Reference
    And collection does not create a curation or training label

  Scenario: Respect the configured recurring cadence
    Given a configured Hacker News Monitor and a two-item feed
    When a scheduled collection is requested before its next due time
    Then no source fetch or registration is performed until due
