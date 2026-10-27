Feature: The router posts every story's lab job first and collects the answers as they finish
  A cold lab job takes about a hundred seconds, and one story used to hold the whole run while it
  waited. The router now sends every candidate story's job without waiting, then spends the rest of
  the run checking all of the outstanding jobs in turn and delivers each story as its answer
  arrives. A job that is still running when the run ends is not an error and does not stop the run.
  It stays recorded on the story, and a short collector task, which posts nothing, delivers it as
  soon as the lab answers. Both take the monitor's single router lock, so they never race.

  Background:
    Given a router that may take up to three stories per run, with a combined Cyclotron endpoint
    And the monitor has collected three stories

  Scenario: Several slow jobs are posted in one run
    Given the lab takes longer than the run's collect window to answer
    When the route task runs
    Then the lab received one decision request for each of the three stories
    And the run ends with the status awaiting and counts three stories awaiting
    And all three stories are still waiting for the router with their jobs recorded
    And nothing was delivered

  Scenario: Jobs that finish during the collect window are delivered in the same run
    Given the lab answers each job after a few checks
    When the route task runs
    Then all three stories are routed and delivered to every publication
    And the lab received one decision request for each of the three stories
    And the run ends complete with nothing awaiting

  Scenario: A job still running at the end of the run is delivered by the collector
    Given the lab takes longer than the run's collect window to answer
    And the route task has run once
    When the lab has answered and the collector runs
    Then all three stories are routed and delivered to every publication
    And the lab still received only one decision request for each of the three stories
    And the collector did not examine feedback

  Scenario: The collector never posts a story that has no job
    Given the router may take only one story per run
    And the lab takes longer than the run's collect window to answer
    And the route task has run once
    When the lab has answered and the collector runs
    Then the first story is routed
    And the other two stories were never sent to the lab

  Scenario: A rerun of the route task does not post a job twice
    Given the lab takes longer than the run's collect window to answer
    And the route task has run once
    When the lab has answered and the route task runs again
    Then the lab still received only one decision request for each of the three stories
    And all three stories are routed and delivered to every publication

  Scenario: The collector waits while the route run holds the lock
    Given the route run holds the router lock
    When the collector runs
    Then the collector reports that the router is locked
    And the lab received no requests

  Scenario: The route run waits while the collector holds the lock
    Given the collector holds the router lock
    When the route task runs
    Then the router reports that it is locked
    And the lab received no requests

  Scenario: A Cyclotron without the combined endpoint is also posted first and collected later
    Given Cyclotron does not have the combined endpoint
    And the router may take only one story per run
    And the lab takes longer than the run's collect window to answer
    When the route task runs
    Then the lab received one request for each publication of the first story
    And the run ends with the status awaiting and counts one story awaiting
    When the lab has answered and the collector runs
    Then the first story is routed
    And the lab still received only one request for each publication of the first story

  Scenario: A refusal from Cyclotron still stops the run
    Given Cyclotron is busy with another run when the router posts
    When the route task runs
    Then the run ends stopped because Cyclotron is busy
