Feature: The router keeps each publication's Cyclotron classifier status for the newsroom home page
  Every hour the router's cyclotron-status task asks the Cyclotron, with its read-only status operation, how each publication's classifier is doing, and
  keeps the latest snapshot in the monitoring table, one row per publication. The Monitoring view serves a signed-in editor only the row of the
  publication that owns the site's own endpoint, even when several publications share one Cyclotron run. The task is its own task with its own lock: it
  never decides anything, a 503 from the Cyclotron means "no snapshot yet" and not "the lab is paused", and a sweep is never stopped by it.

  Background:
    Given a router with three publications on one shared Cyclotron run

  Scenario: A snapshot is kept for each publication and read back for the site's own publication
    When the router runs the cyclotron-status task
    Then each of the three publications has one status row with the snapshot's own as-of time
    And an editor of the first publication's site is served the first publication's snapshot

  Scenario: A publication the Cyclotron has no snapshot for yet has no row and the others are kept
    Given the Cyclotron has no verified snapshot yet for the first publication
    When the router runs the cyclotron-status task
    Then the first publication has no status row and the other two have one
    And an editor of the first publication's site is served no snapshot

  Scenario: Only this publication's output is kept from the Cyclotron's answer
    The Cyclotron answers with the binding's envelope and one snapshot per bound output under "classifiers".
    Given the Cyclotron's answer for the first publication holds only another output's snapshot
    When the router runs the cyclotron-status task
    Then the first publication's run says its answer was not a status snapshot
    And an editor of the first publication's site is served no snapshot

  Scenario: A classifier that has never been retrained is kept as it is reported
    Given the Cyclotron reports no refits and no labels for the first publication
    When the router runs the cyclotron-status task
    Then the first publication's row says zero refits, no last change and zero labels, and invents nothing

  Scenario: An editor sees only this site's output even though the run is shared
    When the router runs the cyclotron-status task
    Then an editor of the second publication's site is served the second publication's snapshot only
    And a reader who is not an editor is refused

  Scenario: A 503 from the status operation does not stop the deciding sweep
    Given the Cyclotron has no verified snapshot yet for the first publication
    When the router runs the cyclotron-status task
    Then the monitor has no lab pause
    When the router then runs a routing sweep
    Then the sweep was not stopped and it posted decisions to the Cyclotron
    And a sweep that is running does not delay the status task, because each has its own lock

  Scenario: The stack runs the task every hour for the shared monitor and for Distinctive Mark
    Then the stack has an hourly cyclotron-status schedule for the hn monitor and one for the web-distinctive monitor
    And neither status schedule retries a failed run
