Feature: An attempt is written before the call
  An attempt entry opens as "started" before the provider is called, and closes as "sent", "refused" or "unknown". An entry left "started" or "unknown" is settled
  by reading what Caducus recorded for that event id (for X, Caducus's own read of the account's recent posts stands behind that record); if Caducus has no
  record, the same event id is handed over again and Caducus dedupes on it, so a post is never made twice. No timeout decides it: an entry with no record yet stays
  open, and the list shows "Outcome unknown" until it is settled.

  Background:
    Given an empty announcement catalog
    And the clock reads "2026-11-17T09:00:00Z"
    And the Story "slow-water" is at version 3
    And the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-17T09:00:00Z" and these Deliveries
      | channel | account  | approval | text        |
      | x       | handle-1 | none     | First words |
    And one worker serves the channel "x" account "handle-1"

  Scenario: The started entry exists before the provider call is made
    When the worker sends the Delivery "x" "handle-1"
    Then the entry for attempt 1 of the Delivery "x" "handle-1" was already "started" when the channel was called
    And the Delivery "x" "handle-1" has these attempts
      | number | outcome |
      | 1      | sent    |

  Scenario: The Delivery is sending while the attempt is open
    Given the channel answers the next new event with "queued"
    When the worker sends the Delivery "x" "handle-1"
    Then the Delivery "x" "handle-1" is "sending"
    And the Delivery "x" "handle-1" has these attempts
      | number | outcome |
      | 1      | started |
    And the Delivery "x" "handle-1" shows "Outcome unknown" for attempt 1

  Scenario: An attempt left started because the worker died is settled without a second post
    Given an attempt is opened for the Delivery "x" "handle-1" and the worker dies before the call
    When the worker settles the Delivery "x" "handle-1"
    Then exactly 1 post was made
    And the Delivery "x" "handle-1" is "sent"
    And the Delivery "x" "handle-1" has these attempts
      | number | outcome |
      | 1      | sent    |

  Scenario: An attempt whose call reached Caducus but whose answer was lost is settled without a second post
    Given the channel answers the next new event with "lands but the answer is lost"
    When the worker sends the Delivery "x" "handle-1"
    Then the call fails
    And the Delivery "x" "handle-1" has these attempts
      | number | outcome | code                      |
      | 1      | unknown | no answer to the hand-over |
    And the Delivery "x" "handle-1" is "sending"
    And the Delivery "x" "handle-1" shows "Outcome unknown" for attempt 1
    When the worker settles the Delivery "x" "handle-1"
    Then exactly 1 post was made
    And the Delivery "x" "handle-1" is "sent"
    And the Delivery "x" "handle-1" has these attempts
      | number | outcome |
      | 1      | sent    |
    And the Delivery row "x" "handle-1" holds
      | field      | value  |
      | providerId | post-1 |

  Scenario: An attempt whose call never arrived is handed over again under the same event id
    Given the channel answers the next new event with "lost"
    When the worker sends the Delivery "x" "handle-1"
    Then the call fails
    And the Delivery "x" "handle-1" has these attempts
      | number | outcome |
      | 1      | unknown |
    When the worker settles the Delivery "x" "handle-1"
    Then exactly 1 post was made
    And the channel was handed the events of attempts "1, 1" of the Delivery "x" "handle-1" in that order
    And the Delivery "x" "handle-1" is "sent"

  Scenario: Nothing decides an open attempt but what the provider recorded
    Given the channel answers the next new event with "queued"
    And the worker sends the Delivery "x" "handle-1"
    When the clock reads "2027-03-01T00:00:00Z"
    And the worker settles the Delivery "x" "handle-1"
    Then the Delivery "x" "handle-1" is "sending"
    And the Delivery "x" "handle-1" has these attempts
      | number | outcome |
      | 1      | started |
    And exactly 0 posts were made
    When Caducus records the post for attempt 1 of the Delivery "x" "handle-1"
    And the worker settles the Delivery "x" "handle-1"
    Then the Delivery "x" "handle-1" is "sent"

  Scenario: No second attempt opens while one has no answer
    Given the channel answers the next new event with "queued"
    And the worker sends the Delivery "x" "handle-1"
    When the worker sends the Delivery "x" "handle-1"
    Then the call is refused saying "settle it before another attempt opens"
    And the Delivery "x" "handle-1" has 1 attempt
    And exactly 0 posts were made

  Scenario: A settled refusal closes the entry with the provider's code
    Given the channel answers the next new event with "queued"
    And the worker sends the Delivery "x" "handle-1"
    When Caducus records that attempt 1 of the Delivery "x" "handle-1" was refused with "account suspended"
    And the worker settles the Delivery "x" "handle-1"
    Then the Delivery "x" "handle-1" is "failed"
    And the Delivery "x" "handle-1" has these attempts
      | number | outcome | code              |
      | 1      | refused | account suspended |
