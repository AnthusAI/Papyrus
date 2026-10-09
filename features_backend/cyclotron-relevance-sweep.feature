Feature: The candidate pipeline asks the relevance cyclotron about pending references
  A worker sweep decides every pending candidate reference, records the
  decisions in the newsroom's records, sends editors' reviews back to the
  cyclotron, writes the status snapshot, and keeps the cyclotron's store in
  the private media bucket so the next worker can continue. It never accepts
  or rejects a reference.

  Background:
    Given a publication with a relevance cyclotron
    And two pending references and one accepted reference

  Scenario: A sweep decides pending references and records the decisions
    When the decide-relevance sweep runs with apply
    Then each pending reference has a current relevance decision
    And the accepted reference has no relevance decision
    And the cyclotron status snapshot is recorded with 2 decisions awaiting review
    And no reference changed its curation status
    And the cyclotron store snapshot is in the private bucket

  Scenario: A fresh worker continues from the private bucket without repeating model calls
    Given the decide-relevance sweep has run with apply
    When the decide-relevance sweep runs with apply on a fresh worker
    Then the decision model was called once per pending reference in total
    And each pending reference still has one current relevance decision

  Scenario: An editor's review reaches the cyclotron
    Given the decide-relevance sweep has run with apply
    And an editor rejected the first pending reference as "out_of_scope" saying "Vendor marketing."
    When the decide-relevance sweep runs with apply
    Then the cyclotron has a label "exclude" for the first pending reference with the explanation "Vendor marketing."
    And the cyclotron status snapshot is recorded with 1 decisions awaiting review

  Scenario: A review that is not about relevance closes the decision without teaching
    Given the decide-relevance sweep has run with apply
    And an editor rejected the first pending reference as "duplicate" saying "Already have it."
    When the decide-relevance sweep runs with apply
    Then the cyclotron has no label for the first pending reference
    And the cyclotron status snapshot is recorded with 1 decisions awaiting review

  Scenario: A second worker cannot sweep while another holds the claim
    Given another worker holds the relevance cyclotron claim
    When the decide-relevance sweep runs with apply
    Then the sweep stops because the cyclotron is claimed
    And the decision model was not called

  Scenario: A dry run lists the work and calls no model
    When the decide-relevance sweep runs without apply
    Then the plan lists 2 pending references to decide
    And the decision model was not called
    And no records were written

  Scenario: An editor's manual review rate reaches the cyclotron once
    Given an editor asked for a 50% review rate for 7 days
    When the decide-relevance sweep runs with apply
    Then the cyclotron status snapshot reports a manual rate of 50% set by "managing-editor"
    When the decide-relevance sweep runs with apply
    Then the cyclotron applied the manual rate once

  Scenario: An editor clears the manual review rate
    Given an editor asked for a 50% review rate for 7 days
    And the decide-relevance sweep has run with apply
    And the editor then asked to clear the manual rate
    When the decide-relevance sweep runs with apply
    Then the cyclotron status snapshot reports no manual rate
