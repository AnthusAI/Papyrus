Feature: The router asks Cyclotron once per story for every publication
  A discovery is relevant to several publications, and all of their classifiers share one native
  decision. The router therefore sends one machine request per story that names every publication's
  binding, polls that one job, and then records each publication's answer exactly as it recorded
  separate answers before, so delivery downstream does not change. A Cyclotron that does not have the
  combined endpoint yet is still served one publication at a time.

  Background:
    Given a router for three publications with a combined Cyclotron endpoint
    And the monitor has collected a story that every publication could use

  Scenario: One request decides the story for all publications
    When the router sweeps the collected story
    Then Cyclotron receives exactly one decision request for the story
    And that request names the binding of all three publications
    And no publication is decided with a request of its own
    And each publication's decision receipt has the same shape as a single-publication receipt
    And the publications that said include are delivered the Reference

  Scenario: A retry of the same story reuses the same request identity
    Given Cyclotron is busy with another run when the router first asks
    When the router sweeps the collected story
    Then the router stops and defers the story
    When Cyclotron is free and the router sweeps again
    Then the story is decided by a request with the same identity as the first attempt

  Scenario: A request identity is derived from the exact content sent
    When the router builds the decision request for the story
    Then building it again gives the same request identity
    And a request with a different set of publication bindings has a different request identity

  Scenario: A changed publication set does not re-post a job the lab already holds
    Given the router has a pending job for the story under the current publication set
    When the publication set changes and the router sweeps again
    Then the stored job is polled and collected
    And the story is not posted again
    And the story is decided and delivered without a conflict

  Scenario: A request conflict leads to exactly one re-post
    Given Cyclotron answers the first request with a request conflict
    When the router sweeps the collected story
    Then the router posts the story a second time under a different request identity
    And the story is decided and delivered

  Scenario: A request conflict that persists is not re-posted a second time
    Given Cyclotron answers every request with a request conflict
    When the router sweeps the collected story
    Then the router posts the story exactly twice
    And the story is still waiting for the router

  Scenario: A Cyclotron without the combined endpoint is served one publication at a time
    Given Cyclotron does not have the combined endpoint yet
    When the router sweeps the collected story
    Then the router asks the combined endpoint once and remembers the answer for the run
    And each publication is decided with its own request
    And the story is delivered exactly as it would have been

  Scenario: A changed binding stops the run without losing the story
    Given Cyclotron reports that a publication binding changed
    When the router sweeps the collected story
    Then the router stops with the reason binding changed
    And the story is still waiting for the router
    When the binding is current and the router sweeps again
    Then the story is decided and delivered

  Scenario: An unrecognised conflict backs the story off and it is asked again on a later run
    Given Cyclotron answers the combined request with a conflict the router does not recognise
    When the router sweeps the collected story
    Then the run does not stop
    And the story is not given up on and waits to be asked again later
    And the run receipt says what Cyclotron answered
    When the router sweeps again before the wait is over
    Then Cyclotron is not asked about the story again
    When Cyclotron stops refusing and the router sweeps after the wait
    Then the story is decided and delivered

  Scenario: A story the lab refuses for now does not hold back the other stories
    Given the lab refuses the first story with a conflict the router does not recognise
    When the router sweeps the collected story
    Then the run does not stop
    And the other story is decided and delivered

  Scenario: A publication whose classifier is not ready is parked while the others carry on
    Given Cyclotron says one publication's criteria are pending inside the combined answer
    When the router sweeps the collected story
    Then that publication is waiting for a classifier
    And the other two publications are decided and delivered

  Scenario: A publication refusal inside the combined answer refuses the story
    Given Cyclotron refuses the story's source for one publication inside the combined answer
    When the router sweeps the collected story
    Then the story is refused
    And the answers of the other publications are kept on the story's receipt

  Scenario: A job left over from an earlier Cyclotron run is still polled and collected
    Given the story holds a combined job that was posted under an earlier Cyclotron run
    When the router sweeps the collected story
    Then the earlier run's job is polled
    And the story is decided and delivered
    And the story is not posted again

  Scenario: A pending job stored under an old-format request id keeps being polled
    Given the story holds a pending combined job stored under an old-format request id
    When the router sweeps the collected story
    And the router sweeps the collected story again
    Then the story is not posted again
    And the story is still waiting for the router

  Scenario: A pending job stored under an old-format request id is collected without a new post
    Given the story holds a combined job that was posted under an old-format request id
    When the router sweeps the collected story
    Then the story is decided and delivered
    And the story is not posted again

  Scenario: A job that ended failed is posted again once
    Given the story holds a combined job that the lab reports as failed
    When the router sweeps the collected story
    Then the story is posted again once
    And the story is decided and delivered

  Scenario: A job the lab no longer knows is posted again once
    Given the story holds a combined job under the current run that the lab answers with not found once
    When the router sweeps the collected story
    Then the story is posted again once
    And the story is decided and delivered

  Scenario: A job the lab keeps denying errors only that story and the run continues
    Given the lab answers not found for every job of the first two stories
    When the router sweeps the collected story
    Then the first story is an error
    And the run is complete rather than stopped


  Scenario: A combined job is only ever polled on the route it was posted to
    When the router sweeps the collected story
    Then every stored job of the story is marked as posted to the decisions route
    And no job of the story was polled on a per-publication route

  Scenario: A job stored before routes were recorded is polled on the decisions route when it is the combined job
    Given a story whose combined job was stored without a recorded route
    When the router sweeps the collected story again
    Then the earlier run's job is polled
    And no job of the story was polled on a per-publication route
