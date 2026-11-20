Feature: Manual mode: Papyrus drafts the words, a person posts them and records the address
  Some posts have no API or no budget, and some are better made by a person from their own account. A Delivery in manual mode covers them. Papyrus drafts the words
  and checks them exactly as it does for an automatic Delivery, but it never sends them. A person posts the words somewhere else and pastes the address of the post.
  The Delivery then reads sent, and its attempt log names that person, not a machine. The record is one operation in the operation table, so the newsroom, the
  command line and an agent's tools all reach the same rules.

  Background:
    Given an empty announcement catalog
    And the clock reads "2026-11-17T09:00:00Z"
    And the Story "slow-water" is at version 3
    And the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-17T09:00:00Z" and these Deliveries
      | channel | account | approval | mode   | state   | text                                  |
      | x       | ryan    | none     | manual | drafted | A look at how slow water shapes stone |
    And one worker serves the channel "x" account "ryan"

  Scenario: The words are drafted and checked like any other Delivery's
    Then the Delivery "x" "ryan" has mode "manual" and is "drafted"
    When the words of the Delivery "x" "ryan" are checked against the Story titled "A look at how slow water shapes stone"
    Then every check on the words passed
    And the Delivery "x" "ryan" has mode "manual" and is "ready"

  Scenario: A person records the address and the attempt names that person
    Given the words of the Delivery "x" "ryan" are checked against the Story titled "A look at how slow water shapes stone"
    When the person "ryan" records the address "https://example.org/ryan/status/1" for the Delivery "x" "ryan"
    Then the record is accepted
    And the Delivery "x" "ryan" is sent with the address "https://example.org/ryan/status/1"
    And the attempt log of the Delivery "x" "ryan" names "ryan"

  Scenario: A manual Delivery is never sent automatically
    Given the words of the Delivery "x" "ryan" are checked against the Story titled "A look at how slow water shapes stone"
    Then the Delivery "x" "ryan" may not go at "2026-11-17T10:00:00Z" because "a person posts it by hand and records the address"
    When the worker sends the Delivery "x" "ryan"
    Then the call is refused saying "manual Delivery"
    And nothing was sent
    And the Delivery "x" "ryan" is not sent and has no address
    And no flag was raised

  Scenario: Recording twice is refused and the first record stands
    Given the words of the Delivery "x" "ryan" are checked against the Story titled "A look at how slow water shapes stone"
    And the person "ryan" records the address "https://example.org/ryan/status/1" for the Delivery "x" "ryan"
    When the person "ellie" records the address "https://example.org/ellie/status/2" for the Delivery "x" "ryan"
    Then the record is refused saying "already sent"
    And the Delivery "x" "ryan" is sent with the address "https://example.org/ryan/status/1"
    And the attempt log of the Delivery "x" "ryan" has 1 entry
    And the attempt log of the Delivery "x" "ryan" names "ryan"

  Scenario Outline: An address that is not a web address is refused
    Given the words of the Delivery "x" "ryan" are checked against the Story titled "A look at how slow water shapes stone"
    When the person "ryan" records the address "<address>" for the Delivery "x" "ryan"
    Then the record is refused saying "starts with http:// or https://"
    And the Delivery "x" "ryan" is not sent and has no address

    Examples:
      | address                       |
      | not an address                |
      | ryan/status/1                 |
      | ftp://example.org/status/1    |
      | javascript:alert(1)           |
      | https://                      |
      | https://example.org/a b       |

  Scenario: Words whose checks failed cannot be recorded as posted
    Given the words of the Delivery "x" "ryan" are checked and the fact check supports nothing
    Then the Delivery "x" "ryan" has mode "manual" and is "blocked"
    When the person "ryan" records the address "https://example.org/ryan/status/1" for the Delivery "x" "ryan"
    Then the record is refused saying "only a ready Delivery"
    And the Delivery "x" "ryan" is not sent and has no address

  Scenario: Words that were never checked cannot be recorded as posted
    When the person "ryan" records the address "https://example.org/ryan/status/1" for the Delivery "x" "ryan"
    Then the record is refused saying "only a ready Delivery"
    And the Delivery "x" "ryan" is not sent and has no address

  Scenario: Only a manual Delivery is recorded by hand
    Given the decision "story-published:other" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-17T09:00:00Z" and these Deliveries
      | channel  | account | approval | text         |
      | linkedin | page    | none     | Automatic one |
    When the person "ryan" records the address "https://example.org/page/1" for the Delivery "linkedin" "page"
    Then the record is refused saying "automatic Delivery"
    And the Delivery "linkedin" "page" is not sent and has no address

  Scenario: A machine does not record that a person posted
    Given the words of the Delivery "x" "ryan" are checked against the Story titled "A look at how slow water shapes stone"
    When an agent tries to record the address "https://example.org/ryan/status/1" for the Delivery "x" "ryan"
    Then the record is refused as "human_required"
    And the Delivery "x" "ryan" is not sent and has no address
