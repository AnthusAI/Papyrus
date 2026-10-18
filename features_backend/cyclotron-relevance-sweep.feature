@requires-cyclotron
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

  Scenario: An editor primes the running cyclotron with a pasted URL
    Given an editor "managing-editor" asked to prime the cyclotron with "https://example.org/vendor-launch" as "exclude" saying "Marketing, not research."
    When the decide-relevance sweep runs with apply
    Then the cyclotron status snapshot reports 1 primed example
    And the cyclotron status snapshot reports the change "Added 1 primed example to the example list."
    And the priming request for "https://example.org/vendor-launch" is applied as version 2
    And each pending reference was decided by version 2

  Scenario: Running the sweep again does not prime the same URL twice
    Given an editor "managing-editor" asked to prime the cyclotron with "https://example.org/vendor-launch" as "exclude" saying "Marketing, not research."
    And the decide-relevance sweep has run with apply
    When the decide-relevance sweep runs with apply
    Then the cyclotron status snapshot reports 1 primed example
    And the page text of "https://example.org/vendor-launch" was extracted once

  Scenario: A request with a label the cyclotron does not have is marked failed
    Given an editor "managing-editor" asked to prime the cyclotron with "https://example.org/vendor-launch" as "maybe" saying "Not sure."
    When the decide-relevance sweep runs with apply
    Then the priming request for "https://example.org/vendor-launch" failed saying "include, exclude"
    And the cyclotron status snapshot reports 0 primed examples
    And each pending reference has a current relevance decision

  Scenario: A URL that cannot be extracted is marked failed and the sweep continues
    Given the page text of "https://example.org/paywalled" cannot be extracted
    And an editor "managing-editor" asked to prime the cyclotron with "https://example.org/paywalled" as "include" saying "A good source."
    When the decide-relevance sweep runs with apply
    Then the priming request for "https://example.org/paywalled" failed saying "could not be read"
    And each pending reference has a current relevance decision

  Scenario: A second request for the same URL with a different label is refused
    Given an editor "managing-editor" asked to prime the cyclotron with "https://example.org/vendor-launch" as "exclude" saying "Marketing, not research."
    And the decide-relevance sweep has run with apply
    And an editor "managing-editor" asked to prime the cyclotron with "https://example.org/vendor-launch" as "include" saying "On second thought."
    When the decide-relevance sweep runs with apply
    Then the priming request for "https://example.org/vendor-launch" failed saying "different"
    And the cyclotron status snapshot reports 1 primed example
