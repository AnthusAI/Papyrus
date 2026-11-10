Feature: The GSI ledger keeps every release to one new index per table
  DynamoDB creates or deletes one global secondary index per table in one update, and a table holds at most 20.
  A CI check compares the indexes of every data model with the last release tag. It fails when a table gains more
  than one index, when an index changes its keys in place, or when a table has more than 18 indexes. It warns
  when a table has 16 or more. It also prints the order in which the pending indexes have to ship, one per table
  in each release. A renamed index counts as a removal plus an addition, which is what DynamoDB does.

  Scenario: Two new indexes on one table fail the build
    Given a change that adds two indexes to Reference
    When CI runs the GSI ledger check
    Then the GSI ledger check fails naming Reference and both indexes

  Scenario: One new index on a table passes and is placed in the first release
    Given a change that adds one index to Reference
    When CI runs the GSI ledger check
    Then the GSI ledger check passes
    And the release order lists Reference's new index in release 1

  Scenario: An index that changes its keys in place fails
    Given a change that changes the keys of an existing Item index
    When CI runs the GSI ledger check
    Then the GSI ledger check fails naming Item and the index

  Scenario: A table near the DynamoDB limit warns
    Given a change that takes a table to 16 indexes
    When CI runs the GSI ledger check
    Then the GSI ledger check passes
    And it warns that the table has 16 of the 20 indexes DynamoDB allows

  Scenario: A table past 18 indexes fails
    Given a change that takes a table to 19 indexes
    When CI runs the GSI ledger check
    Then the GSI ledger check fails naming that table
