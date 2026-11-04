Feature: Newsroom data tables can be restored to a past moment
  Votes, curation decisions and corpus records live in the Amplify Data tables.
  Every site turns on DynamoDB point-in-time recovery for all of them, with no
  site setting, so a bad write can be rolled back to the second before it.

  Scenario: Every data table has point-in-time recovery on
    Given the data tables of a site backend
    When the backend turns on point-in-time recovery
    Then every data table has point-in-time recovery enabled

  Scenario: Turning it on updates tables in place
    Given the data tables of a site backend
    When the backend turns on point-in-time recovery
    Then no table is added, removed or replaced and only the recovery setting changes
