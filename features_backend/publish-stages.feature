Feature: Publishing reports each stage on its own
  Publishing a story does four things: the data is saved as published, the page
  is built, the edge cache is told to drop the old page, and the public address
  can be checked to show the new version. Any later stage can fail, or simply
  not be finished yet, while the earlier ones are done. The command reports each
  stage separately, in words and in a machine-readable result, and exits with a
  different non-zero code for each stage that failed, so a script can tell a
  refused cache purge from a page that was never built, and neither looks like a
  failed save. A page that is still being built when the client stops waiting is
  reported as still running, which is not the same as failed, and running the
  command again is always safe. The client waits longer for the page-building
  call than for an ordinary request.

  Scenario: Every stage worked
    Given a saved story and a page-building function that answers with the pages it wrote
    When the operator runs the publish command and asks to verify it
    Then the command exits with code 0
    And the result lists the pages written
    And the result lists the paths purged at the edge
    And the public page shows the published version

  Scenario: A refused cache purge is not a failed write
    Given a saved story and a page-building function whose cache purge was refused
    When the operator runs the publish command
    Then the command exits with code 6
    And the page is reported as written
    And the result says the failure was in the cache purge, not in the write

  Scenario: A site that leaves the purge off is not a failure
    Given a saved story and a page-building function that skipped the purge because the site leaves it off
    When the operator runs the publish command
    Then the command exits with code 0

  Scenario: Waiting for the public page that still shows the old version
    Given a saved story and a page-building function that answers with the pages it wrote
    And the public address still serves an older version
    When the operator runs the publish command and asks to verify it without waiting
    Then the command exits with code 7
    And the page is reported as written

  Scenario: Without asking to verify, an old public page is only reported
    Given a saved story and a page-building function that answers with the pages it wrote
    And the public address still serves an older version
    When the operator runs the publish command
    Then the command exits with code 0

  Scenario: The client stops waiting while the page is still being built
    Given a saved story and a page-building function that is too slow for the client
    When the operator runs the publish command
    Then the command exits with code 5
    And the result says the page is still running
    And the result does not say the publish failed
    And the story's data stays published

  Scenario: Running the command again after a timeout finishes the job
    Given a saved story and a page-building function that is too slow for the client the first time
    When the operator runs the publish command
    And the operator runs the publish command again
    Then the second run exits with code 0
    And the second run lists the pages written

  Scenario: The function running out of time is a failure that is safe to retry
    Given a saved story and a page-building function that runs out of time
    When the operator runs the publish command
    Then the command exits with code 4
    And the result says that running the command again is safe

  Scenario: The page-building call waits longer than an ordinary request
    Given a saved story and a page-building function that answers with the pages it wrote
    When the operator runs the publish command
    Then the call to the function was allowed to take 120 seconds
