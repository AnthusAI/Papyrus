Feature: The router never gives up on a lab job just because it is slow
  A lab job stays recorded on its story and is polled, with the usual per-job backoff and pacing, until it
  completes, fails, or the lab answers 404. How long it has been pending is not one of those signals, so no
  age ever turns a waiting story into an error. An older limit did exactly that to stories the lab was still
  working on; the reopen-stale-finals task puts those stories back so the collector can deliver them.

  Background:
    Given a router that may take up to three stories per run, with a combined Cyclotron endpoint
    And the monitor has collected three stories

  Scenario: A job pending for a very long time is never finalized and is collected when the lab completes it
    Given the lab takes longer than the run's collect window to answer
    And the route task has run once
    When the collector runs a month later while the lab is still working
    Then all three stories are still waiting for the router with their jobs recorded
    And no story has a final outcome
    When the lab has answered and the collector runs a day later
    Then all three stories are routed and delivered to every publication
    And the lab still received only one decision request for each of the three stories

  Scenario: Reopening restores stories an age limit finalized and the collector then delivers them
    Given the lab takes longer than the run's collect window to answer
    And the route task has run once
    And an earlier age limit finalized the first story as an error with its job still recorded
    And the second story was finalized as an error for another reason
    When the reopen-stale-finals task runs
    Then the task reports one story reopened
    And the first story is waiting for the router again with its job kept
    And the second story is still finalized as an error
    When the lab has answered and the collector runs
    Then the first story is routed

  Scenario: Reopening twice changes nothing the second time
    Given the lab takes longer than the run's collect window to answer
    And the route task has run once
    And an earlier age limit finalized the first story as an error with its job still recorded
    When the reopen-stale-finals task runs
    And the reopen-stale-finals task runs
    Then the task reports no story reopened
