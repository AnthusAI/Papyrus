Feature: An interrupted run is settled, and Outcome unknown is a state, not a guess
  The wake queue gives the runner each message at most twice by design: once to run it, and once to settle it. A message is hidden for the whole
  run, so a second delivery means the first attempt died. On that second delivery the runner reads the wake's run record. A record still started,
  with no outcome, is a run that died, and it is never left looking as if it is still running. If the agent's definition says its procedure is safe
  to repeat, because every write it makes is keyed, the runner runs it once more under the same key and the run ends with its own outcome. If not,
  the runner records the outcome unknown, puts the run on the list of things a person must look at, and stops: a procedure that is not marked safe
  to repeat is never run twice for one wake. No timeout and no retry count decides anything. A third delivery can only mean that settling itself
  crashed, and the queue moves that message to the dead-letter queue, where its alarm fires.

  Background:
    Given a site backend that keeps run records for the procedure "papyrus.example.settle"

  Scenario: A crashed run that is safe to repeat is run once more and ends did it
    Given the wake "settler|manual|1" has a run record that was started and never finished
    And the wake says its procedure is safe to repeat
    When the queue delivers that wake for the 2nd time
    Then the procedure ran 1 time
    And the run record is completed with the outcome "acted" on attempt 2
    And the site holds 1 run record

  Scenario: A crashed run that is not marked safe to repeat ends outcome unknown and is not run again
    Given the wake "settler|manual|1" has a run record that was started and never finished
    And the wake says its procedure is not marked safe to repeat
    When the queue delivers that wake for the 2nd time
    Then the procedure ran 0 times
    And the run record is failed with the outcome "unknown" and the reason "interrupted"
    And the run list shows "! Outcome unknown (interrupted)"
    And the run is on the list of runs that need a person
    And the site holds 1 run record

  Scenario: A wake that carries no word on repeating is treated as not safe to repeat
    Given the wake "settler|manual|1" has a run record that was started and never finished
    And the wake says nothing about repeating its procedure
    When the queue delivers that wake for the 2nd time
    Then the procedure ran 0 times
    And the run record is failed with the outcome "unknown" and the reason "interrupted"

  Scenario: A settled run is not run again on a later redelivery
    Given the wake "settler|manual|1" has a run record that was started and never finished
    And the wake says its procedure is safe to repeat
    And the queue has delivered that wake for the 2nd time
    When the queue delivers that wake for the 2nd time again
    Then the procedure ran 1 time
    And the run record is completed with the outcome "acted" on attempt 2

  Scenario: The first delivery of a wake that already has a run is not a crash
    Given the wake "settler|manual|1" has a run record that was started and never finished
    And the wake says its procedure is safe to repeat
    When the queue delivers that wake for the 1st time
    Then the procedure ran 0 times
    And the delivery is reported as a duplicate of the first run
    And the run record is still started

  Scenario: A crash while settling leaves the message on the queue, and the queue dead-letters it on the next delivery
    Given the wake "settler|manual|1" has a run record that was started and never finished
    And the wake says its procedure is not marked safe to repeat
    And the site backend refuses to record the outcome
    When the queue delivers that wake for the 2nd time and settling crashes
    Then the delivery fails, so the message stays on the queue
    And the run record is still started
    And the wake queue moves a message to its dead-letter queue after 2 deliveries
