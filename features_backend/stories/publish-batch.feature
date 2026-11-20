Feature: Publishing several versions builds their pages once
  A backfill of translations used to publish one version at a time, and each publish took the site's projection lease for its own page build, so a run of N
  publishes fought a deploy N times. `papyrus ops content publish --id A --id B ...` (the signed-in lane) saves every version, queues each Story's page build
  without starting one, asks the site once to build the queue, and waits for every job. The site builds the whole queue in one invocation, under one hold of the
  lease. A site that keeps no publish job records cannot queue, so it says so and publishes nothing by batch.

  Scenario: Three versions are saved, queued without a build each, and drained once
    Given a signed-in lane and three saved versions
    When the three versions are published as a batch
    Then every version is queued with no build of its own
    And the site is asked exactly once to build the queue
    And each version's job is asked about until it is done

  Scenario: The site builds everything queued under one hold of the lease
    Given the site's publish jobs and two published Stories queued by a batch
    When the one drain runs
    Then both Stories are built
    And the projection lease was taken once
