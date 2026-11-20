Feature: A correction is made only for a Delivery that went out, and a retry or a rival never writes the wrong words
  A correction of a Delivery is three ordered writes with nothing to hold them together: the new Delivery with its words, the old Delivery marked superseded
  and pointing forward, and the "supersedes" link. A crash can stop after any of them, and a retry finishes whatever is missing from a fresh read of the old Delivery.
  A different correction is not a retry: when the new Delivery already exists and its words are other than the ones this caller brings, someone else already
  corrected it, and the caller is told so; nothing of the second caller's words is written under the first caller's Delivery. A Delivery that never went out is
  edited, not corrected, and a Delivery with an attempt that has no answer yet is settled first, because until then nobody knows whether a post exists.

  Background:
    Given an empty announcement catalog
    And the clock reads "2026-11-17T09:00:00Z"
    And the Story "slow-water" is at version 3
    And the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-17T09:00:00Z" and these Deliveries
      | channel | account  | approval | text        |
      | x       | handle-1 | none     | First words |
    And one worker serves the channel "x" account "handle-1"

  # --- only a Delivery that went out is corrected ---------------------------------------------------------------------------------------------------

  Scenario: A Delivery that is ready but never went out is not corrected
    When the person "ellie" corrects the Delivery "x" "handle-1" with the words "Corrected words"
    Then the call is refused saying "not sent"
    And the catalog holds 1 Delivery
    And the Delivery "x" "handle-1" generation 1 is "ready"

  Scenario: A draft that never went out is not corrected
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval | text |
      | email   | site-one | none     |      |
    When the person "ellie" corrects the Delivery "email" "site-one" with the words "Corrected words"
    Then the call is refused saying "not sent"
    And the catalog holds 2 Deliveries

  Scenario: A Delivery with an attempt that has no answer is not corrected
    Given the channel answers the next new event with "queued"
    And the worker sends the Delivery "x" "handle-1"
    When the person "ellie" corrects the Delivery "x" "handle-1" with the words "Corrected words"
    Then the call is refused saying "settled before a correction is made"
    And the catalog holds 1 Delivery

  Scenario: A Delivery that went out is corrected
    Given the worker sends the Delivery "x" "handle-1"
    When the person "ellie" corrects the Delivery "x" "handle-1" with the words "Corrected words"
    Then the catalog holds 2 Deliveries
    And the Delivery "x" "handle-1" generation 1 is superseded by generation 2

  # --- a crash after each of the three writes is finished by a retry with a fresh read ---------------------------------------------------------------

  Scenario: A crash after the new Delivery's row, before its words, is finished by a retry
    Given the Delivery "x" "handle-1" has been sent
    And the next upload of a Delivery's words fails as if the connection dropped
    When the person "ellie" corrects the Delivery "x" "handle-1" with the words "Corrected words"
    Then the call fails
    And the Delivery "x" "handle-1" has no words yet
    And the Delivery "x" "handle-1" generation 1 is "sent"
    When the person "ellie" corrects generation 1 of "x" "handle-1" with the words "Corrected words"
    Then the call went through
    And the catalog holds 2 Deliveries
    And generation 2 of "x" "handle-1" has these words in S3 "Corrected words"
    And the Delivery "x" "handle-1" generation 1 is superseded by generation 2
    And generation 2 of "x" "handle-1" is linked to generation 1 by a supersedes relation

  Scenario: A crash after the new Delivery is whole, before the old one is marked, is finished by a retry
    Given the Delivery "x" "handle-1" has been sent
    And the next update of a Delivery fails as if the connection dropped
    When the person "ellie" corrects the Delivery "x" "handle-1" with the words "Corrected words"
    Then the call fails
    And the Delivery "x" "handle-1" generation 1 is "sent"
    When the person "ellie" corrects generation 1 of "x" "handle-1" with the words "Corrected words"
    Then the catalog holds 2 Deliveries
    And the Delivery "x" "handle-1" generation 1 is superseded by generation 2
    And generation 2 of "x" "handle-1" is linked to generation 1 by a supersedes relation

  Scenario: A crash after the old one is marked, before the relation, is finished by a retry with a fresh read
    Given the Delivery "x" "handle-1" has been sent
    And the next write of a relation fails as if the connection dropped
    When the person "ellie" corrects the Delivery "x" "handle-1" with the words "Corrected words"
    Then the call fails
    And the Delivery "x" "handle-1" generation 1 is superseded by generation 2
    When the person "ellie" corrects generation 1 of "x" "handle-1" with the words "Corrected words"
    Then the call went through
    And the catalog holds 2 Deliveries
    And generation 2 of "x" "handle-1" is linked to generation 1 by a supersedes relation
    And the live Delivery of "x" "handle-1" is generation 2

  Scenario: A retry from a copy read before the crash finishes the same way
    Given the Delivery "x" "handle-1" has been sent
    And "ellie" has read the Delivery "x" "handle-1" before anyone corrects it
    And the next write of a relation fails as if the connection dropped
    When the person "ellie" corrects the Delivery "x" "handle-1" with the words "Corrected words"
    Then the call fails
    When "ellie" corrects the Delivery they read with the words "Corrected words"
    Then the call went through
    And generation 2 of "x" "handle-1" is linked to generation 1 by a supersedes relation

  # --- two different corrections at once: one winner, one conflict ----------------------------------------------------------------------------------

  Scenario: Two people correct the same Delivery with different words
    Given the Delivery "x" "handle-1" has been sent
    And "ellie" has read the Delivery "x" "handle-1" before anyone corrects it
    And "sierra" has read the Delivery "x" "handle-1" before anyone corrects it
    When "ellie" corrects the Delivery they read with the words "Ellie's words"
    And "sierra" corrects the Delivery they read with the words "Sierra's words"
    Then the call is refused saying "already corrected"
    And the call is refused saying "different words"
    And the catalog holds 2 Deliveries
    And generation 2 of "x" "handle-1" has these words in S3 "Ellie's words"
    And the Delivery "x" "handle-1" generation 1 is superseded by generation 2
    And the live Delivery of "x" "handle-1" is generation 2

  Scenario: A rival's different words are not written under a half-finished correction
    Given the Delivery "x" "handle-1" has been sent
    And "sierra" has read the Delivery "x" "handle-1" before anyone corrects it
    And the next upload of a Delivery's words fails as if the connection dropped
    When the person "ellie" corrects the Delivery "x" "handle-1" with the words "Ellie's words"
    Then the call fails
    When "sierra" corrects the Delivery they read with the words "Sierra's words"
    Then the call is refused saying "different words"
    And the Delivery "x" "handle-1" has no words yet
    When the person "ellie" corrects generation 1 of "x" "handle-1" with the words "Ellie's words"
    Then generation 2 of "x" "handle-1" has these words in S3 "Ellie's words"
    And the Delivery "x" "handle-1" generation 1 is superseded by generation 2

  Scenario: The same correction made twice is one correction
    Given the Delivery "x" "handle-1" has been sent
    And "ellie" has read the Delivery "x" "handle-1" before anyone corrects it
    When the person "ellie" corrects the Delivery "x" "handle-1" with the words "Corrected words"
    And "ellie" corrects the Delivery they read with the words "Corrected words"
    Then the call went through
    And the catalog holds 2 Deliveries
