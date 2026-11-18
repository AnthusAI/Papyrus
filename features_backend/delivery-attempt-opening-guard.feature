Feature: An attempt opens only on a Delivery that may be sent
  Before an attempt opens, the Delivery must be the highest generation for its Announcement, channel and account, must not be superseded, and its words file must
  exist and match the row's content hash. Otherwise nothing is sent and one flag is raised. Closing an attempt never changes the state of a superseded Delivery:
  its outcome goes in the log and the state stays superseded. A Delivery with an attempt that has no answer yet is not corrected until the attempt is settled.

  Background:
    Given an empty announcement catalog
    And the clock reads "2026-11-17T09:00:00Z"
    And the Story "slow-water" is at version 3
    And the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-17T09:00:00Z" and these Deliveries
      | channel | account  | approval | text        |
      | x       | handle-1 | none     | First words |
    And one worker serves the channel "x" account "handle-1"

  Scenario: An attempt never opens on a lower generation
    Given the Delivery "x" "handle-1" has been sent
    And the next update of a Delivery fails as if the connection dropped
    When the person "ellie" corrects generation 1 of "x" "handle-1" with the words "Corrected words"
    Then the call fails
    When the worker sends generation 1 of "x" "handle-1"
    Then the call is refused saying "a newer generation exists"
    And nothing was sent
    And generation 1 of "x" "handle-1" has no attempts
    And exactly 1 flag was raised about generation 1 of "x" "handle-1"

  Scenario: An attempt never opens on a superseded Delivery
    Given the Delivery "x" "handle-1" has been sent
    And the person "ellie" corrects the Delivery "x" "handle-1" with the words "Corrected words"
    When the worker sends generation 1 of "x" "handle-1"
    Then the call is refused saying "superseded"
    And nothing was sent
    And exactly 1 flag was raised about generation 1 of "x" "handle-1"

  Scenario: Asking twice raises the flag once
    Given the Delivery "x" "handle-1" has been sent
    And the person "ellie" corrects the Delivery "x" "handle-1" with the words "Corrected words"
    When the worker sends generation 1 of "x" "handle-1"
    And the worker sends generation 1 of "x" "handle-1"
    Then exactly 1 flag was raised about generation 1 of "x" "handle-1"

  Scenario: A ready Delivery whose words file is missing is not sent
    Given the words file of the Delivery "x" "handle-1" is lost
    When the worker sends the Delivery "x" "handle-1"
    Then the call is refused saying "its words file is missing"
    And nothing was sent
    And the Delivery "x" "handle-1" has no attempts
    And exactly 1 flag was raised about the Delivery "x" "handle-1"

  Scenario: A words file that does not match the content hash is not sent
    Given the words file of the Delivery "x" "handle-1" is replaced by "Words nobody checked"
    When the worker sends the Delivery "x" "handle-1"
    Then the call is refused saying "does not match the row's content hash"
    And nothing was sent
    And exactly 1 flag was raised about the Delivery "x" "handle-1"

  Scenario: A Delivery that is only waiting raises no flag
    Given the clock reads "2026-11-17T08:00:00Z"
    When the worker sends the Delivery "x" "handle-1"
    Then the call is refused saying "waiting for its release time"
    And nothing was sent
    And no flag was raised

  Scenario: A Delivery already sent is not sent again and raises no flag
    Given the worker sends the Delivery "x" "handle-1"
    When the worker sends the Delivery "x" "handle-1"
    Then the call is refused saying "not waiting to be sent"
    And exactly 1 post was made
    And no flag was raised

  Scenario: An attempt that closes after its Delivery was superseded records its outcome and does not revive the Delivery
    Given the channel answers the next new event with "queued"
    And the worker sends the Delivery "x" "handle-1"
    And Caducus records the post for attempt 1 of the Delivery "x" "handle-1"
    And the Delivery "x" "handle-1" is marked superseded by a correction made elsewhere
    When the worker settles the Delivery "x" "handle-1"
    Then the Delivery "x" "handle-1" generation 1 is "superseded"
    And generation 1 of "x" "handle-1" has these attempts
      | number | outcome |
      | 1      | sent    |
    And the Delivery row "x" "handle-1" holds
      | field      | value  |
      | providerId | post-1 |

  Scenario: A close that finds the Delivery changed since it was read applies to what is there now
    Given the channel answers the next new event with "queued"
    And the worker sends the Delivery "x" "handle-1"
    And Caducus records the post for attempt 1 of the Delivery "x" "handle-1"
    And the Delivery "x" "handle-1" changes under the worker just before the close
    When the worker settles the Delivery "x" "handle-1"
    Then the Delivery "x" "handle-1" generation 1 is "superseded"
    And generation 1 of "x" "handle-1" has these attempts
      | number | outcome |
      | 1      | sent    |

  Scenario: A Delivery with an attempt that has no answer is not corrected
    Given the channel answers the next new event with "queued"
    And the worker sends the Delivery "x" "handle-1"
    When the person "ellie" corrects the Delivery "x" "handle-1" with the words "Corrected words"
    Then the call is refused saying "settled before a correction is made"
    And the catalog holds 1 Delivery

  Scenario: A settled Delivery may be corrected
    Given the worker sends the Delivery "x" "handle-1"
    When the person "ellie" corrects the Delivery "x" "handle-1" with the words "Corrected words"
    Then the Delivery "x" "handle-1" generation 1 is superseded by generation 2
