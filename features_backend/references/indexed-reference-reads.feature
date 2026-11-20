@backend @indexed-reference-reads
Feature: Commands that touch a few References read those rows through indexes, never a whole table
  A command that works on one Reference, a few, or one batch of writes asks the backend for exactly those rows: the Reference by id or lineage,
  its attachments by lineage, its relations by state key. The Reference, ReferenceAttachment and SemanticRelation tables hold thousands of rows,
  and a command run once per Reference used to read all of them each time. A command that really must visit every row says so. Nothing here
  touches production: the backend is in memory and counts its requests.

  Scenario: Writing a new version of one Reference reads that lineage only
    Given a publication with 300 References and 300 relations
    When a new version of one Reference is prepared for writing
    Then no whole table was listed
    And the previous version is superseded

  Scenario: Naming one Reference to process reads that Reference and its attachments only
    Given a publication with 300 References and 300 relations
    When the targeted scope of one named Reference is built
    Then no whole table was listed
    And the scope holds that Reference and its attachments

  Scenario: A citation graph reads the whole table only when it looks at it
    Given a publication with 300 References and 300 relations
    When the targeted scope of one named Reference is built
    And the citation lookup is not used
    Then no whole table was listed
    When the citation lookup is used
    Then the Reference table was listed once
