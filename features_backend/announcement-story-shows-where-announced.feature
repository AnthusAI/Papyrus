Feature: A Story shows where it was announced
  The Announcements of a Story are read through the "announces" relation, from the Story's side, in one indexed query. Each Announcement then gives its live
  Deliveries, one line per channel, from the Deliveries index of that Announcement. An account's Deliveries are read newest first through the account index.
  Nothing lists a table: the specs run on a backend that has no call to list one.

  Background:
    Given an empty announcement catalog
    And the clock reads "2026-11-16T14:00:00Z"
    And the Story "slow-water" is at version 3

  Scenario: One line per channel under one decision
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval |
      | x       | handle-1 | none     |
      | email   | site-one | soft     |
    When the Story "slow-water" is asked where it was announced
    Then it answers with 1 Announcement of kind "story_published" with these lines
      | channel | account  |
      | email   | site-one |
      | x       | handle-1 |
    And every read was an index query or a get by id

  Scenario: A Story that was never announced answers with nothing
    When the Story "slow-water" is asked where it was announced
    Then it answers with 0 Announcements

  Scenario: A correction shows only the live Delivery
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval | text        |
      | x       | handle-1 | none     | First words |
    And the person "ellie" corrects the Delivery "x" "handle-1" with the words "Corrected words"
    When the Story "slow-water" is asked where it was announced
    Then it answers with 1 Announcement of kind "story_published" with these lines
      | channel | account  |
      | x       | handle-1 |
    And the line for "x" "handle-1" is generation 2

  Scenario: An account's Deliveries come newest first
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval |
      | x       | handle-1 | none     |
    And the clock reads "2026-11-16T15:00:00Z"
    And the decision "story-published:tide-tables" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval |
      | x       | handle-1 | none     |
    When the Deliveries of the account "x" "handle-1" are read newest first
    Then they come in this order of creation
      | created              |
      | 2026-11-16T15:00:00Z |
      | 2026-11-16T14:00:00Z |

  Scenario: The calendar reads planned Announcements by release time
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-17T09:00:00Z" and these Deliveries
      | channel | account  | approval |
      | x       | handle-1 | none     |
    And the decision "story-published:tide-tables" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-25T09:00:00Z" and these Deliveries
      | channel | account  | approval |
      | x       | handle-1 | none     |
    When the calendar asks for the planned Announcements from "2026-11-16T00:00:00Z" to "2026-11-20T00:00:00Z"
    Then it is told about the Announcement "story-published:slow-water" only
