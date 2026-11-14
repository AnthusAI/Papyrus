Feature: The router keeps each publication's Cyclotron classifier status for the newsroom home page
  Every hour the router's cyclotron-status task asks the Cyclotron, with its read-only status operation, how each publication's classifier is doing, and
  keeps the latest snapshot in the monitoring table, one row per publication. In the same pass it reads the Cyclotron's read-only report operation and keeps
  this publication's own output beside the snapshot in the same row: the learning state, agreement with reviewers, the held-out evaluation, label counts and the
  decision elements behind the classification. The two reads are independent: a read that fails never erases the other, or its own last good value. The Monitoring view serves a signed-in editor only the row of the
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
    And the Cyclotron's report operation is failing for every publication
    When the router runs the cyclotron-status task
    Then the first publication has no status row and the other two have one
    And an editor of the first publication's site is served no snapshot

  Scenario: Only this publication's output is kept from the Cyclotron's answer
    The Cyclotron answers with the binding's envelope and one snapshot per bound output under "classifiers".
    Given the Cyclotron's answer for the first publication holds only another output's snapshot
    And the Cyclotron's report operation is failing for every publication
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
    And the Cyclotron's report operation is failing for every publication
    When the router runs the cyclotron-status task
    Then the monitor has no lab pause
    When the router then runs a routing sweep
    Then the sweep was not stopped and it posted decisions to the Cyclotron
    And a sweep that is running does not delay the status task, because each has its own lock

  Scenario: The report is kept in the same row as the status, with the Cyclotron's own shape
    When the router runs the cyclotron-status task
    Then each of the three publications's status row also holds its own output's report and the time it was read
    And the status and the report requests carry no request id and an empty payload
    And an editor of the first publication's site is served the status and the report of the first publication only

  Scenario: A report is kept before the first decision, when the status has none
    The report answers 200 even before a first decision, and says in words why its sections are empty.
    Given the Cyclotron has no verified snapshot yet for the first publication
    When the router runs the cyclotron-status task
    Then the first publication's row holds a report and no status
    And an editor of the first publication's site is served that report with a null status
    And the monitor has no lab pause

  Scenario: A report that fails is a failed read, never a lab pause, and the last report is kept
    Given the router has already kept a report for the first publication
    And the Cyclotron's report operation is failing for every publication
    When the router runs the cyclotron-status task again
    Then the first publication's row still holds the earlier report and its earlier read time
    And the report reads were refused as ordinary failed reads
    And the monitor has no lab pause

  Scenario: A failed status keeps the last status and a new report is still kept
    Given the router has already kept a report for the first publication
    And the Cyclotron has no verified snapshot yet for the first publication
    When the router runs the cyclotron-status task again
    Then the first publication's row still holds the earlier status and also the new report

  Scenario: A report for another output is never kept
    Given the Cyclotron's report for the first publication holds only another output's report
    When the router runs the cyclotron-status task
    Then the first publication's run says its answer was not a classifier report
    And the first publication's row holds no report

  Scenario: A very large report is cut down to fit the table's item limit and says so
    Given the Cyclotron's report for the first publication carries a very large model
    When the router runs the cyclotron-status task
    Then the first publication's stored report is under the item limit and says what was left out

  Scenario: The stack runs the task every hour for the shared monitor and for Distinctive Mark
    Then the stack has an hourly cyclotron-status schedule for the hn monitor and one for the web-distinctive monitor
    And neither status schedule retries a failed run
