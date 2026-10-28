Feature: The router can hold lab decisions while still sending editor feedback
  While the lab cannot take decisions, the router config can hold them. Nothing is posted to the
  decision endpoints, but editors' votes still reach Cyclotron.

  Scenario: Feedback is sent while decisions are held
    Given a router with feedback on and three delivered stories
    And the router holds decisions
    When an editor accepts a reference in the newsroom UI
    And the feedback task runs
    Then one feedback was sent to Cyclotron with the label include
    And no decision request was sent after the hold

  Scenario: A held router posts no decision for a new story
    Given a live router with a collected story that holds decisions
    When the held router runs
    Then no decision request was sent by the held router
    And the receipt says decisions were held

  Scenario: A canary run posts exactly one decision and then stops
    Given a live router with three collected stories and a combined decision endpoint
    When the router runs as a canary allowed one decision
    Then exactly one decision request was sent
    And the receipt says the run stopped by max decisions
    And the result names the posted request and job

  Scenario: A canary run counts per-publication decisions together
    Given a live router with three collected stories and no combined endpoint
    When the router runs as a canary allowed two decisions
    Then exactly two decision requests were sent
    And the receipt says the run stopped by max decisions

  Scenario: A hold override posts the canary while the configuration still holds decisions
    Given a live router with a collected story that holds decisions
    When the router runs as a canary allowed one decision with the hold overridden
    Then exactly one decision request was sent
    And the result names the posted request and job
    And the stored configuration still holds decisions
    And a later normal run posts nothing and says decisions were held

  Scenario: Without the canary options a run behaves as before
    Given a live router with three collected stories and no combined endpoint
    When the router runs normally
    Then nine decision requests were sent
    And the run was not stopped by max decisions
