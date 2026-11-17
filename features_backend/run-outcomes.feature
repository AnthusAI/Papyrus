Feature: Every finished run ends with one of five outcomes
  A run of a newsroom procedure has two separate facts. The run status is the mechanics: queued,
  running, completed or failed. The outcome is the answer to "what came of it?", and it is written
  only when the run finishes. There are exactly five outcomes. "Did it" means the run changed
  records. "Nothing to do" means it looked and nothing needed doing; it is not a failure, and it
  always says why with a short reason code. "Asked" means it raised a review request for a person and
  stopped. "Failed" means it could not do the work and nothing half-done is left looking done.
  "Outcome unknown" means it started and no result was recorded; the runner never guesses that, so
  nothing in this feature sets it. A procedure says "nothing to do" or "asked" by returning a
  run_outcome and a run_outcome_reason; a procedure that says nothing about it did its work. Every
  outcome is shown as a word with a mark, never as a colour alone. Runs recorded before outcomes
  existed are never rewritten; they say so.

  Scenario: A run that does its work is recorded as did it
    Given a procedure that finishes and returns a title
    When the runner runs it
    Then the run is recorded as completed with the outcome "acted"
    And the run result carries the outcome "acted"

  Scenario: A run that looks and finds nothing records nothing to do with a reason, and is not a failure
    Given a procedure that looks at a feed and returns run_outcome "nothing" with run_outcome_reason "no_new_filing"
    When the runner runs it
    Then the run is recorded as completed with the outcome "nothing"
    And the outcome reason is "no_new_filing"
    And no error is recorded on the run

  Scenario: A run that says it found nothing but not why is a failed run
    Given a procedure that returns run_outcome "nothing" with no run_outcome_reason
    When the runner runs it
    Then the run is recorded as failed with the outcome "failed"
    And the outcome reason is "invalid_outcome"
    And the run's error says a nothing-to-do outcome needs a reason

  Scenario: A run that raises a review request is recorded as asked
    Given a procedure that raises a review request and returns run_outcome "asked" with run_outcome_reason "needs_editor_decision"
    When the runner runs it
    Then the run is recorded as completed with the outcome "asked"
    And the outcome reason is "needs_editor_decision"

  Scenario: A procedure error is recorded as failed
    Given a procedure that stops with an error
    When the runner runs it
    Then the run is recorded as failed with the outcome "failed"
    And the outcome reason is "procedure_error"
    And the error is kept on the run

  Scenario: A run that runs out of time is recorded as failed with its own reason
    Given a procedure that runs past its deadline
    When the runner runs it
    Then the run is recorded as failed with the outcome "failed"
    And the outcome reason is "timed_out"

  Scenario: A procedure cannot give itself an outcome outside the vocabulary
    Given a procedure that returns run_outcome "unknown" with run_outcome_reason "lost"
    When the runner runs it
    Then the run is recorded as failed with the outcome "failed"
    And the outcome reason is "invalid_outcome"

  Scenario: A run records what it was started for
    Given a story-stage automation started a procedure for the story "story-a" at version "v-3"
    When the runner runs it
    Then the run records the automation id and the subject "Story" "story-a" at version "v-3"

  Scenario: A run that nothing started for a subject records no subject
    Given a procedure that finishes and returns a title
    When the runner runs it
    Then the run records no subject

  Scenario: The trigger row that started a run carries the same outcome
    Given a trigger row for a run that found nothing to do for the reason "no_new_filing"
    When the runner records the trigger row
    Then the trigger row says the outcome is "nothing" with the reason "no_new_filing"

  Scenario: A request the runner could not accept is a failed outcome on its trigger row
    Given a trigger row for a request the runner refused
    When the runner records the trigger row
    Then the trigger row says the outcome is "failed" with the reason "not_runnable"

  Scenario Outline: The run list shows each outcome as a word with a mark
    Given a finished run recorded with the outcome "<outcome>"
    When an operator reads the run list
    Then the run is shown as "<shown>"

    Examples:
      | outcome | shown                 |
      | acted   | ✓ Did it              |
      | nothing | – Nothing to do       |
      | asked   | ? Asked               |
      | failed  | ✗ Failed              |
      | unknown | ! Outcome unknown     |

  Scenario: The run list gives the reason beside the outcome
    Given a finished run that found nothing to do for the reason "no_new_filing"
    When an operator reads the run list
    Then the run is shown as "– Nothing to do (no_new_filing)"

  Scenario: An older run says it was recorded before outcomes and is not rewritten
    Given a finished run recorded before outcomes existed
    When an operator reads the run list
    Then the run is shown as "Recorded before outcomes"
    And the stored run still has no outcome

  Scenario: A run that has not finished has no outcome yet
    Given a run that is still running
    When an operator reads the run list
    Then the run is shown as "Not finished yet"

  Scenario: The command line prints the outcome in words
    Given a finished run that found nothing to do for the reason "no_new_filing"
    When an operator runs "automations runs --id distinctive.ttab"
    Then the output has a run line containing "– Nothing to do (no_new_filing)"
