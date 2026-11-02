Feature: Automatic acceptance runs as its own task, once per publication, with the whole time budget
  Automatic acceptance used to run at the end of every routing run, after the sweep and the feedback pass. Those stages used the
  Lambda's time, and a pass that started with less than the reserve left was skipped: it was skipped in about one run of every four.
  It is cheap beside routing, so it no longer follows the routing run. Every hour the router starts one invocation per publication
  whose automatic acceptance is on; each has its own lock and the Lambda's whole time budget, and a routing run never touches it.

  Background:
    Given a router with three publications

  Scenario: A routing run does not run automatic acceptance
    When the router runs a routing pass
    Then no publication had an automatic acceptance pass in that run

  Scenario: The hourly task only starts one run for each publication
    When the router runs the auto-accept task without naming a publication
    Then it started one run for each of the three publications
    And it took no lock and wrote no receipt

  Scenario: A publication whose automatic acceptance is switched off is not started
    Given automatic acceptance is switched off for the second publication
    When the router runs the auto-accept task without naming a publication
    Then it started runs for the first and third publications only

  Scenario: A run that names a publication works on that publication alone
    When the router runs the auto-accept task for the second publication
    Then only the second publication had an automatic acceptance pass

  Scenario: A run that names an unknown publication is refused
    When the router runs the auto-accept task for a publication the monitor does not list
    Then the run is refused as an unknown publication and does nothing

  Scenario: One publication's run does not block routing or another publication's run
    Given the second publication's auto-accept run is in progress
    When the router runs the auto-accept task for the second publication
    Then that run reports that it is locked
    And the routing lock is free
    And the first publication's auto-accept lock is free

  Scenario: The stack schedules the task every hour for the shared monitor and for Distinctive Mark
    Then the stack has an hourly auto-accept schedule for the hn monitor and one for the web-distinctive monitor
    And neither schedule retries a failed run
