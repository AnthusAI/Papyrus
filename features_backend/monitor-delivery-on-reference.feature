Feature: A monitor delivery records its monitor on the Reference and writes no Message
  Messages come only from people. When a monitor delivers a Reference, the Reference itself
  records which monitor found it and what the source said about it. Readers (the weekly
  Knowledge Map, monitor stories, the rule-monitor auto-accept) read those fields; nothing
  reads a provenance Message or an ingestion rationale relation.

  Scenario: A new delivery carries its monitor and details and leaves no Message behind
    Given a monitor named "huggingface" delivering to a publication
    When it delivers a model with structured details
    Then the new Reference names the monitor "huggingface" and holds the details
    And the delivery wrote no Message and no relation
    And the delivery receipt has no provenance Message id

  Scenario: A rule monitor's delivery records its rule on the Reference
    Given a monitor named "hn" delivering to a publication
    When it delivers an item chosen by its direct rule
    Then the new Reference holds the direct rule

  Scenario: A Reference found by two monitors keeps the first and its curation is untouched
    Given a monitor named "hn" delivering to a publication
    And an accepted Reference that another monitor delivered first
    When it delivers the same document
    Then the Reference still names the first monitor
    And no field of the Reference is written

  Scenario: The weekly Knowledge Map reads a delivered model from its Reference alone
    Given a delivered model Reference with the Hub details on it
    When the monitor records are loaded
    Then the record has the model id and the likes from the Reference
    And no relation was queried

  Scenario: The backfill copies old provenance onto the Reference and a dry run writes nothing
    Given a Reference delivered before the fields existed, with an old provenance relation
    When the monitor delivery backfill runs as a dry run
    Then it counts one planned update and writes nothing
    When the monitor delivery backfill runs for real
    Then the Reference names the monitor and holds the details from the old relation
