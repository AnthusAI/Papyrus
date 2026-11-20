Feature: One live Delivery for each Announcement, channel and account
  A Delivery is made once for an Announcement, a channel and an account. A corrected version is a new Delivery that names the one it replaces. Its id carries a
  generation, and it is created with a condition, so two corrections of one Delivery cannot both win. AppSync has no transaction across writes, so a correction
  of a Delivery that went out is three ordered writes that a retry finishes: the new Delivery, the old one marked superseded and pointing forward, and the "supersedes" link. The live
  Delivery of a channel and account is always the highest generation. A superseded Delivery waits for nothing.

  Background:
    Given an empty announcement catalog
    And the clock reads "2026-11-16T14:00:00Z"
    And the Story "slow-water" is at version 3
    And the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-17T09:00:00Z" and these Deliveries
      | channel | account  | approval | text        |
      | x       | handle-1 | none     | First words |

  Scenario: A second live Delivery without supersedes is refused
    When a second Delivery for "x" "handle-1" is made on that Announcement without naming one to replace
    Then the call is refused saying "name it with supersede"
    And the catalog holds 1 Delivery

  Scenario: A correction replaces the old Delivery, with both links and the relation
    Given the Delivery "x" "handle-1" has been sent
    When the person "ellie" corrects the Delivery "x" "handle-1" with the words "Corrected words"
    Then the catalog holds 2 Deliveries
    And the Delivery "x" "handle-1" generation 1 is superseded by generation 2
    And the Delivery "x" "handle-1" generation 2 supersedes generation 1
    And generation 2 of "x" "handle-1" is linked to generation 1 by a supersedes relation
    And the live Delivery of "x" "handle-1" is generation 2
    And generation 2 of "x" "handle-1" has these words in S3 "Corrected words"

  Scenario: A crash after the new Delivery finishes on retry
    Given the Delivery "x" "handle-1" has been sent
    And the next update of a Delivery fails as if the connection dropped
    When the person "ellie" corrects generation 1 of "x" "handle-1" with the words "Corrected words"
    Then the call fails
    And the live Delivery of "x" "handle-1" is generation 2
    When the person "ellie" corrects generation 1 of "x" "handle-1" with the words "Corrected words"
    Then the catalog holds 2 Deliveries
    And the Delivery "x" "handle-1" generation 1 is superseded by generation 2
    And generation 2 of "x" "handle-1" is linked to generation 1 by a supersedes relation

  Scenario: A Delivery that was corrected cannot be corrected again with other words
    Given the Delivery "x" "handle-1" has been sent
    And the person "ellie" corrects the Delivery "x" "handle-1" with the words "Corrected words"
    When the person "ellie" corrects generation 1 of "x" "handle-1" with the words "Other words"
    Then the call is refused saying "already corrected"
    And the catalog holds 2 Deliveries

  Scenario: The correction of a correction is generation 3
    Given the Delivery "x" "handle-1" has been sent
    And the person "ellie" corrects the Delivery "x" "handle-1" with the words "Corrected words"
    And generation 2 of "x" "handle-1" has been sent
    When the person "ellie" corrects generation 2 of "x" "handle-1" with the words "Corrected twice"
    Then the live Delivery of "x" "handle-1" is generation 3
    And the Delivery "x" "handle-1" generation 2 is superseded by generation 3

  Scenario: Another channel or another account has its own live Delivery
    When the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval | text        |
      | x       | handle-2 | none     | Other words |
      | email   | site-one | none     | Mail words  |
    Then the Announcement has 3 live Deliveries

  Scenario: A superseded Delivery waits for nothing
    Given the Delivery "x" "handle-1" has been sent
    And the person "ellie" corrects the Delivery "x" "handle-1" with the words "Corrected words"
    Then the Delivery "x" "handle-1" generation 1 has no due time
    And the Delivery "x" "handle-1" generation 1 is not in the due index

  Scenario: A correction is for the same channel and account
    When the person "ellie" corrects the Delivery "x" "handle-1" with the words "Words" on the account "handle-9"
    Then the call is refused saying "same channel and account"
