Feature: A unit of work longer than one run finishes across several runs
  A run is a short wake-up and the runner has fifteen minutes. When one unit of work, such as translating a long Story, cannot finish in that time,
  the procedure saves its progress on the records it is changing and ends "Did it", asking in its output for its next run at a time. Before the run is
  recorded the runner sets one follow-up timer for that time, and the next run is a wake of its own with its own key, run record and cost. It re-reads
  the records and carries on: progress never lives in a model's transcript. Two limits stop a chain that would never end. A chain may continue only a
  fixed number of times, and a run that asks for one more ends "Failed" with the reason that the limit was reached. And a continuation is decided by the
  same gate as any paid wake, so it starts nothing once the site's budget is reached. A run that asks for a continuation that cannot be set ends
  "Failed", never "Did it", because its work is not done.

  Background:
    Given a site backend with a published procedure for continuation "papyrus.example.long"

  Scenario: A run that asks for its next run has one timer set for it and ends did it
    When the procedure finishes part of its work and asks for its next run at "2026-11-21T09:00:00Z"
    Then the continuation run record is completed with the outcome "acted"
    And one timer is set for "2026-11-21T09:00:00Z" whose wake key ends in "|c1"
    And the timer's wake is the same procedure with the same input and the same trigger, marked as a continuation 1

  Scenario: A continuation asks for another and the key counts up in the same chain
    Given the run is itself continuation 1 of the chain that began with run "run-root"
    When the procedure finishes part of its work and asks for its next run at "2026-11-22T09:00:00Z"
    Then one timer is set for "2026-11-22T09:00:00Z" whose wake key ends in "|c2"
    And the wake key names the chain's first run "run-root"

  Scenario: A chain that has continued as many times as it may is stopped
    Given the run is itself continuation 8 of the chain that began with run "run-root"
    When the procedure finishes part of its work and asks for its next run at "2026-11-22T09:00:00Z"
    Then the continuation run record is failed with the outcome "failed" and the reason "continuation_limit_reached"
    And no timer is set

  Scenario: A run that finishes its work and asks for nothing sets no timer
    When the procedure finishes all of its work
    Then the continuation run record is completed with the outcome "acted"
    And no timer is set

  Scenario: A next run time that is not a UTC instant fails the run
    When the procedure finishes part of its work and asks for its next run at "tomorrow morning"
    Then the continuation run record is failed with the outcome "failed" and the reason "invalid_continuation"
    And no timer is set

  Scenario: A timer that cannot be set fails the run instead of leaving it looking done
    Given the timer service refuses the timer
    When the procedure finishes part of its work and asks for its next run at "2026-11-21T09:00:00Z"
    Then the continuation run record is failed with the outcome "failed" and the reason "continuation_not_scheduled"

  Scenario: A run on a runner with no timer service fails when it asks for a continuation
    Given the runner has no timer service
    When the procedure finishes part of its work and asks for its next run at "2026-11-21T09:00:00Z"
    Then the continuation run record is failed with the outcome "failed" and the reason "continuation_not_scheduled"
