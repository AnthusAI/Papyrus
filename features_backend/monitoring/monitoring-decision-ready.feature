Feature: A decision-ready event rings the router's doorbell
  When the Cyclotron lab finishes a decision job it sends a "Decision Ready" event to the Papyrus
  doorbell bus. The event is only a doorbell. It never carries a decision, and nothing in it is
  delivered. It makes the router run its collect task now, instead of waiting up to two minutes for
  the scheduled collector. The collect task fetches each finished answer with the signed request,
  exactly as it always does, under the monitor's own router lock. The doorbell does not trust the
  lab's item names to pick a monitor: it collects for every monitor whose router configuration is
  bound to the event's Account and run. Events for another run or Account are ignored, malformed
  events are dropped quietly, and the scheduled runs behave exactly as before.

  Background:
    Given a router that may take up to three stories per run, with a combined Cyclotron endpoint
    And the monitor has collected three stories
    And the lab takes longer than the run's collect window to answer
    And the route task has run once

  Scenario: A decision-ready event collects and delivers the finished jobs
    Given the lab has answered every job
    When a decision-ready event arrives for the router's Account and run
    Then the doorbell collected the monitor
    And all three stories are routed and delivered to every publication

  Scenario: An event for an old run is ignored
    Given the lab has answered every job
    When a decision-ready event arrives for an old run
    Then the doorbell ignored the event
    And nothing was delivered

  Scenario: A malformed event is dropped without an error
    Given the lab has answered every job
    When a malformed decision-ready event arrives
    Then the doorbell dropped the event as malformed
    And nothing was delivered

  Scenario: A duplicate event is harmless
    Given the lab has answered every job
    When a decision-ready event arrives for the router's Account and run
    And the same decision-ready event arrives again
    Then all three stories are routed and delivered to every publication
    And each story was delivered to each publication only once

  Scenario: A locked monitor is skipped
    Given the route run holds the router lock
    And the lab has answered every job
    When a decision-ready event arrives for the router's Account and run
    Then the doorbell found the monitor locked
    And nothing was delivered

  Scenario: Scheduled events are unchanged
    When a scheduled collect event arrives
    Then it is not treated as a decision-ready event
