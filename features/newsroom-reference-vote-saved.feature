@brand-agnostic
Feature: A saved vote is reported as saved
  A vote (accept, reject, archive or reopen) is recorded on the Reference and writes no Message: Messages
  come only from people. The newsroom must take the vote's own response as the sign that it was saved,
  and must not wait for a Message or relation the vote no longer writes.

  Scenario: Accepting without an explanation is reported as saved
    Given a pending Reference in the newsroom
    When an editor accepts it without writing why
    Then the newsroom reports the accept as saved
    And no Message and no relation were written

  Scenario: Accepting with an explanation is reported as saved
    Given a pending Reference in the newsroom
    When an editor accepts it and writes why
    Then the newsroom reports the accept as saved

  Scenario: A response for another Reference, or a refused save, is not taken as saved
    Given a pending Reference in the newsroom
    When the save response names another Reference, or says it was not saved
    Then the newsroom says the vote was not saved
