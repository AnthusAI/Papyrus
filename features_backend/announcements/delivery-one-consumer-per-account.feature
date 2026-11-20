Feature: One worker for each channel account
  All attempts for one channel account pass through one consumer, for every channel, so two attempts for one account never race and a rate limit or a budget
  stop is seen by the one place that sends. The worker for an account refuses a Delivery of another account. (The queue that gives the worker its single
  consumer belongs to each channel's infrastructure; this is the rule that consumer keeps.)

  Background:
    Given an empty announcement catalog
    And the clock reads "2026-11-17T09:00:00Z"
    And the Story "slow-water" is at version 3
    And the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-17T09:00:00Z" and these Deliveries
      | channel | account  | approval | text        |
      | x       | handle-1 | none     | First words |
      | x       | handle-2 | none     | Other words |
      | email   | site-one | none     | Mail words  |
    And one worker serves the channel "x" account "handle-1"
    And one worker serves the channel "x" account "handle-2"
    And one worker serves the channel "email" account "site-one"

  Scenario: Every attempt for an account passes through that account's worker
    When the worker for "x" "handle-1" sends the Delivery "x" "handle-1"
    And the person "ellie" corrects the Delivery "x" "handle-1" with the words "Corrected words"
    And the worker for "x" "handle-1" sends the Delivery "x" "handle-1"
    And the worker for "x" "handle-2" sends the Delivery "x" "handle-2"
    Then the worker for "x" "handle-1" handled 2 attempts
    And the worker for "x" "handle-2" handled 1 attempt

  Scenario: A worker refuses a Delivery of another account
    When the worker for "x" "handle-2" sends the Delivery "x" "handle-1"
    Then the call is refused saying "the only consumer of x#handle-2"
    And the Delivery "x" "handle-1" has no attempts
    And nothing was sent

  Scenario: A worker refuses a Delivery of another channel
    When the worker for "email" "site-one" sends the Delivery "x" "handle-1"
    Then the call is refused saying "the only consumer of email#site-one"
    And nothing was sent

  Scenario: The same rule holds for a channel that is not X
    When the worker for "email" "site-one" sends the Delivery "email" "site-one"
    Then the Delivery "email" "site-one" is "sent"
    And the Delivery "email" "site-one" has these attempts
      | number | outcome |
      | 1      | sent    |

  Scenario: Two workers racing to open an attempt on one Delivery: one opens it and the other is told the Delivery changed
    When two workers read the Delivery "x" "handle-1" and both open an attempt
    Then exactly one attempt is written and the other is told the Delivery changed
