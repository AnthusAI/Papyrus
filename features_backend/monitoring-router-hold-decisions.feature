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
