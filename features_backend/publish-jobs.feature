Feature: A publish is answered at once and its page follows
  AppSync gives the newsroom's functions about thirty seconds to answer, and
  building the pages of a publish on a large site can take longer. A publish
  that waited for its pages therefore always looked like a failure to the
  editor, although the page went live a minute or two later; the editor retried,
  and the retry waited two minutes for the site's projection lease and failed.
  Now the CLI's publish saves the data, starts the build in the background and
  is answered at once with a job id; it then asks about the job in short calls
  until the page is live, or says the page is still being built, which is not a
  failure. Publishing the same story again while its build is queued or running
  joins that build. A build that finds the site busy waits a few seconds at
  most, leaves its story queued, and whoever holds the lease builds the queue
  before letting go; Lambda's retry of the busy build then finds the work done.

  Scenario: The publish answers with a job and builds nothing itself
    Given a story ready to publish on a site that keeps build records
    When the editor publishes it from the CLI
    Then the answer says the page is being built, with a job id and the page's address
    And exactly one build is started

  Scenario: Publishing the same story again joins the build
    Given a story ready to publish on a site that keeps build records
    When the editor publishes it from the CLI
    And publishes it again before the build has started
    Then the second answer names the same job
    And exactly one build is started

  Scenario: The status follows the build to its end
    Given a story ready to publish on a site that keeps build records
    When the editor publishes it from the CLI
    And the build runs
    Then asking for the job's status says it is done and names the page it wrote

  Scenario: A busy site queues the build instead of failing it after two minutes
    Given two stories ready to publish on a site that keeps build records
    When the editor publishes both from the CLI
    And the second build starts while another projection holds the lease
    Then the second build waits a few seconds at most and leaves its story queued
    When the first build runs
    Then it builds the queued story too before letting go of the lease
    And the retry of the second build finds its page already built

  Scenario: The CLI waits for the job in short calls
    Given a page-building function that answers with a job and later reports it done
    When the operator's CLI publishes the story
    Then it reports the page as built, with the pages written
    And no call it made had to wait for the build

  Scenario: The CLI says still building when the build outlasts its wait
    Given a page-building function that answers with a job that stays queued
    When the operator's CLI publishes the story
    Then it reports the page as still being built, which is not a failure, and names the job
