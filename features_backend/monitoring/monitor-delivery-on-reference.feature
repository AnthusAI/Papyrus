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

  Scenario Outline: A run of deliveries reads the Reference table once, not once per delivery
    The identity gate has to see the whole Reference table to prove that a delivered item is new, and a table is read 100 rows to a request. A web monitor
    delivers 25 to 40 items in a run, so reading the table for each of them multiplied the cost of the table by that many. A run now reads it once and
    puts each Reference it creates into its copy, so a later delivery of the same document still finds the earlier one.
    Given a publication that already holds <size> References
    When a run delivers 30 new items through one shared listing
    Then the table was read <pages> requests in all
    And a run that read the table for each delivery would have made more than <pages> requests
    And the 30 items became 30 References

    Examples:
      | size | pages |
      | 200  | 2     |
      | 5000 | 50    |

  Scenario: Two deliveries of one document in a run make one Reference
    Given a publication that already holds 5 References
    When a run delivers the same document twice through one shared listing
    Then there is one new Reference and the second delivery reused it
