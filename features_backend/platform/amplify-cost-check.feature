Feature: The monthly Amplify cost is checked from one command
  Amplify bills build minutes, and the October bill showed how fast they add up. The command
  papyrus-infra cost amplify asks Cost Explorer for the AWS Amplify service by usage type and account for each
  month, lists the build minutes of every app from its job durations, and learns a budget threshold from the
  months already billed. The command only reads. The budget itself is a write, so the command prints the exact
  commands for a person to review and run, and never runs them.

  Scenario: Cost Explorer's numbers are listed by month, usage type and account
    Given an account whose Amplify bill has risen for four months
    When the operator checks the Amplify cost for the three months through October
    Then October's build duration is listed in minutes with its cost
    And October's total cost is listed

  Scenario: Build minutes are split per app
    Given an account whose Amplify bill has risen for four months
    When the operator checks the Amplify cost for the three months through October
    Then each app that built in October is listed with its build minutes and build count
    And an app that did not build in October is not listed

  Scenario: The budget threshold is derived from history, not a constant
    Given an account whose Amplify bill has risen for four months
    And a second account whose Amplify bill has been flat for four months
    When the operator plans the budget for each account
    Then the two thresholds differ
    And the flat account's threshold equals its monthly cost

  Scenario: The budget is only planned, never created
    Given an account whose Amplify bill has risen for four months
    When the operator plans the budget for the account
    Then the budget commands are printed for review
    And the commands name the alert address by its parameter and never print an address
