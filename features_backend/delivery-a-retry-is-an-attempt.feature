Feature: A retry is an attempt
  A Delivery keeps a log of its attempts, and the log only grows. Each entry has the attempt's number, the time it opened, the Caducus event id, the outcome and
  the provider's code. Attempt N is one Caducus event with the id "delivery:<deliveryId>:a<N>", so a retry is a new event and the same attempt handed over twice
  posts once. A pause, a budget stop or a rate limit ends an attempt, and the next try is the next attempt on the same Delivery. Nothing counts attempts or stops
  after some number of them: a sequence ends on a clear answer from the provider. There is no "round" in an event id any more.

  Background:
    Given an empty announcement catalog
    And the clock reads "2026-11-17T09:00:00Z"
    And the Story "slow-water" is at version 3
    And the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-17T09:00:00Z" and these Deliveries
      | channel | account  | approval | text        |
      | x       | handle-1 | none     | First words |
    And one worker serves the channel "x" account "handle-1"

  Scenario: A failed attempt and then a successful one are one Delivery with two entries
    Given the channel answers the next new event with "failed" and "duplicate content"
    When the worker sends the Delivery "x" "handle-1"
    Then the Delivery "x" "handle-1" is "failed"
    And the Delivery "x" "handle-1" has these attempts
      | number | outcome | code              |
      | 1      | refused | duplicate content |
    When the person "ellie" sets the Delivery "x" "handle-1" ready to try again
    And the worker sends the Delivery "x" "handle-1"
    Then the Delivery "x" "handle-1" is "sent"
    And the Delivery "x" "handle-1" has these attempts
      | number | outcome | code              |
      | 1      | refused | duplicate content |
      | 2      | sent    |                   |
    And the catalog holds 1 Delivery

  Scenario: Attempt N is the Caducus event delivery:<id>:aN
    Given the channel answers the next new event with "failed" and "duplicate content"
    When the worker sends the Delivery "x" "handle-1"
    And the person "ellie" sets the Delivery "x" "handle-1" ready to try again
    And the worker sends the Delivery "x" "handle-1"
    Then every attempt of the Delivery "x" "handle-1" has the event id delivery:<the Delivery id>:a<its number>
    And the channel was handed the events of attempts "1, 2" of the Delivery "x" "handle-1" in that order
    And no event of the Delivery "x" "handle-1" carries a round suffix

  Scenario: A success records the post, the cost and the attempt
    When the worker sends the Delivery "x" "handle-1"
    Then the Delivery row "x" "handle-1" holds
      | field      | value   |
      | state      | sent    |
      | providerId | post-1  |
      | cost       | 0.200   |
    And the Delivery "x" "handle-1" has these attempts
      | number | outcome | code |
      | 1      | sent    |      |
    And the Delivery "x" "handle-1" has no due time

  Scenario: A pause ends the attempt and the next try is the next attempt
    Given the channel answers the next new event with "refused" and "paused"
    When the worker sends the Delivery "x" "handle-1"
    Then the Delivery row "x" "handle-1" holds
      | field         | value  |
      | state         | blocked |
      | blockedReason | paused |
    And the Delivery "x" "handle-1" has these attempts
      | number | outcome | code   |
      | 1      | refused | paused |
    When the worker sends the Delivery "x" "handle-1"
    Then the call is refused saying "not waiting to be sent"
    When the person "ellie" lifts the pause on the Delivery "x" "handle-1"
    And the worker sends the Delivery "x" "handle-1"
    Then the Delivery "x" "handle-1" is "sent"
    And the Delivery "x" "handle-1" has these attempts
      | number | outcome | code   |
      | 1      | refused | paused |
      | 2      | sent    |        |

  Scenario: A budget stop ends the attempt and names when the budget cycle begins
    Given the channel answers the next new event with "refused" and "budget reached" until "2026-12-01T00:00:00Z"
    When the worker sends the Delivery "x" "handle-1"
    Then the Delivery row "x" "handle-1" holds
      | field         | value                |
      | state         | blocked              |
      | blockedReason | budget reached       |
      | waitingFor    | budget cycle         |
      | nextAttemptAt | 2026-12-01T00:00:00Z |
    And the Delivery "x" "handle-1" is due at "2026-12-01T00:00:00Z"
    When the clock reads "2026-11-30T12:00:00Z"
    And the worker sends the Delivery "x" "handle-1"
    Then the call is refused saying "waiting for budget cycle"
    And the Delivery "x" "handle-1" has 1 attempt
    When the clock reads "2026-12-01T00:00:00Z"
    And the worker sends the Delivery "x" "handle-1"
    Then the Delivery "x" "handle-1" is "sent"
    And the Delivery "x" "handle-1" has 2 attempts

  Scenario: A rate limit ends the attempt, records when to try again, and the next try is the next attempt
    Given the channel answers the next new event with "rate limit" until "2026-11-17T09:15:00Z"
    When the worker sends the Delivery "x" "handle-1"
    Then the Delivery row "x" "handle-1" holds
      | field         | value                |
      | state         | ready                |
      | waitingFor    | rate limit           |
      | nextAttemptAt | 2026-11-17T09:15:00Z |
    And the Delivery "x" "handle-1" has these attempts
      | number | outcome | code       |
      | 1      | refused | rate limit |
    And the Delivery "x" "handle-1" is due at "2026-11-17T09:15:00Z"
    When the clock reads "2026-11-17T09:10:00Z"
    And the worker sends the Delivery "x" "handle-1"
    Then the call is refused saying "waiting for rate limit"
    And the Delivery "x" "handle-1" has 1 attempt
    When the clock reads "2026-11-17T09:15:00Z"
    And the worker sends the Delivery "x" "handle-1"
    Then the Delivery "x" "handle-1" is "sent"
    And the Delivery "x" "handle-1" has these attempts
      | number | outcome | code       |
      | 1      | refused | rate limit |
      | 2      | sent    |            |
    And the Delivery row "x" "handle-1" has no field "nextAttemptAt"
    And the Delivery row "x" "handle-1" has no field "waitingFor"

  Scenario: A rate limit names the time to try again
    Given an attempt is opened for the Delivery "x" "handle-1" and the worker dies before the call
    When the attempt 1 of the Delivery "x" "handle-1" is closed as "refused" with the code "rate limit" and no time
    Then the call is refused saying "names the time"

  Scenario: Earlier entries never change
    Given the channel answers the next new event with "refused" and "paused"
    And the worker sends the Delivery "x" "handle-1"
    And the log of the Delivery "x" "handle-1" is remembered
    When the person "ellie" lifts the pause on the Delivery "x" "handle-1"
    And the worker sends the Delivery "x" "handle-1"
    Then the remembered entries of the Delivery "x" "handle-1" are exactly as they were
    When the attempt 1 of the Delivery "x" "handle-1" is closed as "sent"
    Then the call is refused saying "an earlier entry never changes"

  Scenario: Nothing limits how many attempts a Delivery may have
    Given the channel answers the next new event with "failed" and "code one"
    And the channel answers the next new event with "failed" and "code two"
    And the channel answers the next new event with "failed" and "code three"
    When the worker sends the Delivery "x" "handle-1"
    And the person "ellie" sets the Delivery "x" "handle-1" ready to try again
    And the worker sends the Delivery "x" "handle-1"
    And the person "ellie" sets the Delivery "x" "handle-1" ready to try again
    And the worker sends the Delivery "x" "handle-1"
    And the person "ellie" sets the Delivery "x" "handle-1" ready to try again
    And the worker sends the Delivery "x" "handle-1"
    Then the Delivery "x" "handle-1" is "sent"
    And the Delivery "x" "handle-1" has 4 attempts

  Scenario: The attempt log holds no text
    When the worker sends the Delivery "x" "handle-1"
    Then the Delivery row "x" "handle-1" contains none of "First words" anywhere
