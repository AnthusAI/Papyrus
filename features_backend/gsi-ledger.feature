Feature: The GSI ledger keeps every release to one new index per table, and to what the build timeout allows
  DynamoDB creates or deletes one global secondary index per table in one update, and a table holds at most 20.
  A CI check compares the indexes of every data model with the last release tag. It fails when a table gains more
  than one index, when an index changes its keys in place, or when a table has more than 20 indexes, the limit
  DynamoDB sets. For every table whose indexes changed it reports how many index slots are left. It also prints the
  order in which the pending indexes have to ship, one per table in each release. A renamed index counts as a removal plus an addition, which is what DynamoDB does.
  It also budgets the number of tables that gain an index in one release. Machines on Machines job 107 (2026-11-14) created
  23 indexes in 3,250 seconds of CloudFormation time and was stopped by Amplify's 30 minute build timeout. The check
  derives how many index creations fit from the MEASURED seconds per creation in scripts/data/gsi-deploy-measurements.json,
  the build timeout (cms.buildTimeoutMinutes, 120 by default), the minutes the build reserves for the rest (10) and a
  safety margin stored in the same file (25 percent). Indexes created with a new table do not count: they take seconds.
  Re-measure after a release with scripts/measure-gsi-deploy.ts and append the result to the file.

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

  Scenario: A changed table reports the index slots it has left
    Given a change that takes a table to 20 indexes
    When CI runs the GSI ledger check
    Then the GSI ledger check passes
    And it reports that the table has 20 of 20 indexes with 0 left

  Scenario: A table past the DynamoDB limit fails
    Given a change that takes a table to 21 indexes
    When CI runs the GSI ledger check
    Then the GSI ledger check fails naming that table

  Scenario: A checkout without release tags fails loudly
    When CI runs the GSI ledger check in a checkout without release tags
    Then the GSI ledger check fails saying no release tag was found

  Scenario: A release that adds too many index creations fails CI
    Given a change that adds one new index to each of 40 tables
    And the measured time per index creation makes that more than the build timeout less 10 minutes
    When CI runs the GSI ledger check
    Then the GSI ledger check fails saying 35 index creations fit one release and naming the tables
    And it lists which indexes belong in release 1 and 2

  Scenario: A shorter build timeout splits the same release into three
    Given a change that adds one new index to each of 40 tables
    When CI runs the GSI ledger check with a build timeout of 60 minutes
    Then the GSI ledger check fails saying 15 index creations fit one release and naming the tables
    And it lists which indexes belong in release 1, 2 and 3

  Scenario: A table that is new in the release is created with all its indexes
    Given a change that adds a new table with three indexes
    When CI runs the GSI ledger check
    Then the GSI ledger check passes
    And no index of the new table is listed as waiting for a later release

  Scenario: A release that fits the budget passes
    Given a change that adds one new index to each of 5 tables
    When CI runs the GSI ledger check
    Then the GSI ledger check passes
    And it prints its estimated deploy minutes

  Scenario: The measured time is recorded
    Given a release whose backend update finished
    When its CloudFormation events are read by scripts/measure-gsi-deploy.ts
    Then its data stack duration and index creation count are appended to the ledger's measurements
    # Executable in scripts/test-gsi-ledger.ts (dataStackSeconds, parseMeasurementFile); the append runs against a real stack.
