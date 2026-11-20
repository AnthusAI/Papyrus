Feature: One run per wake, recorded before the work starts
  Every wake that starts a procedure carries a key that says what it is about. A change to a record is
  named by the agent, the record, the record's version and what happened: a story at version 7
  entered a stage. A timer is named by the agent and the time it was scheduled for. A person's
  request, such as Run now or a command-line run, is named by the agent and the request's own id.
  The run's record gets its id from the key and is created only if no record with that id exists, so
  the same wake delivered twice finds its record already there and never runs a second time. The
  record is made, marked started, before the procedure is even loaded, so a run that dies leaves
  evidence of itself. A wake with no key, or a malformed one, does not run.

  Background:
    Given a site with a published procedure "newsroom.fact-check"

  Scenario: The same change delivered twice runs once
    When the wake "fact-check|story-1|v7|story.stage_entered" is delivered
    And the wake "fact-check|story-1|v7|story.stage_entered" is delivered again
    Then the procedure ran 1 time
    And the site holds 1 run record
    And the second delivery is reported as a duplicate of the first run

  Scenario: A redelivered timer runs once
    When the wake "rating|schedule|2026-11-17T08:00:00Z" is delivered
    And the wake "rating|schedule|2026-11-17T08:00:00Z" is delivered again
    Then the procedure ran 1 time
    And the site holds 1 run record

  Scenario: Two versions of one story run once each
    When the wake "fact-check|story-1|v7|story.stage_entered" is delivered
    And the wake "fact-check|story-1|v8|story.stage_entered" is delivered
    Then the procedure ran 2 times
    And the site holds 2 run records

  Scenario: A manual run has its own key and runs alongside a scheduled run of the same agent
    When the wake "rating|schedule|2026-11-17T08:00:00Z" is delivered
    And the wake "rating|manual|request-41" is delivered
    Then the procedure ran 2 times
    And the site holds 2 run records

  Scenario: The record is started before the procedure is loaded
    When the wake "fact-check|story-1|v7|story.stage_entered" is delivered
    Then the first thing the site is asked is to start a run record
    And the run record was made with the status "started" and the wake key
    And the procedure was loaded after the record existed

  Scenario: A procedure that cannot be loaded leaves a failed record, not a started one
    Given the procedure is not published
    When the wake "fact-check|story-1|v7|story.stage_entered" is delivered and refused
    Then the run record says it failed because the procedure was not runnable

  Scenario Outline: A wake with no usable key does not run
    When a run is requested with the wake key "<key>"
    Then the request is refused for its wake key
    And the site holds 0 run records

    Examples:
      | key                         |
      | (none)                      |
      | fact-check                  |
      | fact-check\|story-1\|v7\|   |
      | fact-check\|daily\|x        |

  Scenario: The keys are built from their parts
    Then the change key for "fact-check", "story-1", "v7" and "story.stage_entered" is "fact-check|story-1|v7|story.stage_entered"
    And the timer key for "rating" at "2026-11-17T08:00:00Z" is "rating|schedule|2026-11-17T08:00:00Z"
    And the manual key for "rating" and request "request-41" is "rating|manual|request-41"
    And the change key for a Reference with no versions says "unversioned"
    And a start that no automation governs is owned by its procedure
    And a part that contains the separator is refused
