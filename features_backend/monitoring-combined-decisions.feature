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
