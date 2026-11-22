Feature: An attempt is handed to Caducus under its attempt event id
  Papyrus hands the channel one event for each attempt of a Delivery, and the event id is "delivery:<deliveryId>:a<N>" where N is the attempt's number. Caducus
  treats an event id as an opaque string, so these specs send through the worker, the channel's entry point in Papyrus, into the released Caducus (the pinned
  0.3.0 router, its x channel, its delivery log and a fake X account) and read what Caducus recorded. A retry is the next attempt and so a new event. There is no
  round number and no ":r" suffix anywhere in an event id. No network, no AWS, nothing is posted.

  Background:
    Given an empty announcement catalog
    And the clock reads "2026-11-17T09:00:00Z"
    And the Story "slow-water" is at version 3
    And the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-17T09:00:00Z" and these Deliveries
      | channel | account  | approval | text        |
      | x       | handle-1 | none     | First words |
    And one worker serves the channel "x" account "handle-1" through the released Caducus

  Scenario: A send uses the attempt event id
    When the worker sends the Delivery "x" "handle-1"
    Then the Delivery "x" "handle-1" is "sent"
    And Caducus recorded exactly these events for the Delivery "x" "handle-1"
      | event id                         | status |
      | delivery:<the Delivery id>:a1    | sent   |
    And the fake X account received 1 post with the text "First words"

  Scenario: A retry uses the next attempt number, never a round suffix
    Given the fake X account refuses the next post with "403 Forbidden"
    When the worker sends the Delivery "x" "handle-1"
    Then the Delivery "x" "handle-1" is "failed"
    When the person "ellie" sets the Delivery "x" "handle-1" ready to try again
    And the worker sends the Delivery "x" "handle-1"
    Then the Delivery "x" "handle-1" is "sent"
    And Caducus recorded exactly these events for the Delivery "x" "handle-1"
      | event id                         | status |
      | delivery:<the Delivery id>:a1    | failed |
      | delivery:<the Delivery id>:a2    | sent   |
    And no event id Caducus recorded carries a round suffix
    And the fake X account received 1 post with the text "First words"

  Scenario: The site's X function posts a queued attempt and the Delivery is marked sent
    Given the channel leaves each post on the X queue for the site's X function
    When the worker sends the Delivery "x" "handle-1"
    Then the Delivery "x" "handle-1" is "sending"
    When the site's X function takes the queued post
    Then the Delivery "x" "handle-1" is "sent"
    And the fake X account received 1 post with the text "First words"

  Scenario: The same queue message taken twice settles again and never posts twice
    Given the channel leaves each post on the X queue for the site's X function
    When the worker sends the Delivery "x" "handle-1"
    And the site's X function takes the queued post
    And the site's X function takes the queued post
    Then the Delivery "x" "handle-1" is "sent"
    And the fake X account received 1 post with the text "First words"
