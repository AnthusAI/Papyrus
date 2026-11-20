Feature: An announcement is decided once
  An Announcement is the decision to say something about one or more Stories. It knows nothing about channels: no account, no words, no approval. Each
  channel's version of the decision is a Delivery, written with the Announcement. The decision has a once-only key, such as "story-published:" and the
  Story's lineage, and the Announcement's id is made from that key and created with a condition. So the same Story published twice finds the first decision
  instead of making a second one, and a publish that qualifies on no channel leaves no row at all. The Stories an Announcement is about are "announces" links
  that name the version of each Story that was looked at.

  Background:
    Given an empty announcement catalog
    And the clock reads "2026-11-16T14:00:00Z"
    And the Story "slow-water" is at version 3

  Scenario: The same Story published twice makes one Announcement
    When the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval |
      | email   | site-one | none     |
    And the same decision is made again for the Story "slow-water" with those Deliveries
    Then the catalog holds 1 Announcement
    And the catalog holds 1 Delivery
    And the second call found the Announcement that already existed
    And the Announcement for the key "story-published:slow-water" is found through the key index

  Scenario: A crash between the key and the first Delivery finishes on retry
    Given the next write of a Delivery fails as if the connection dropped
    When the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval |
      | email   | site-one | none     |
    Then the call fails
    And the catalog holds 1 Announcement
    And the catalog holds 0 Deliveries
    When the same decision is made again for the Story "slow-water" with those Deliveries
    Then the catalog holds 1 Announcement
    And the catalog holds 1 Delivery
    And the Announcement is linked to the Story "slow-water" at version 3

  Scenario: A crash after the Delivery row and before its words finishes on retry
    Given the next upload of a Delivery's words fails as if the connection dropped
    When the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval |
      | email   | site-one | none     |
    Then the call fails
    And the catalog holds 1 Delivery
    And the Delivery "email" "site-one" has no words yet
    When the same decision is made again for the Story "slow-water" with those Deliveries
    Then the catalog holds 1 Delivery
    And the Delivery "email" "site-one" has its words in S3

  Scenario: A publish that qualifies on no channel leaves no row
    When the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account | approval |
    Then no Announcement was made
    And the catalog holds 0 Announcements
    And the catalog holds 0 Deliveries
    And the catalog holds 0 links

  Scenario: Two Deliveries on two channels share one Announcement
    When the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel  | account  | approval |
      | email    | site-one | none     |
      | x        | handle-1 | hard     |
    Then the catalog holds 1 Announcement
    And the catalog holds 2 Deliveries
    And both Deliveries belong to that Announcement

  Scenario: A roundup announces many Stories, each at the version that was looked at
    Given the Story "tide-tables" is at version 1
    When the decision "roundup:list-one:2026-w46" of kind "roundup" is made for the Stories "slow-water, tide-tables" with these Deliveries
      | channel | account  | approval |
      | email   | site-one | soft     |
    Then the Announcement is linked to the Story "slow-water" at version 3
    And the Announcement is linked to the Story "tide-tables" at version 1

  Scenario: Different once-only keys are different decisions
    When the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval |
      | email   | site-one | none     |
    And the decision "correction:slow-water:4" of kind "correction" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval |
      | email   | site-one | none     |
    Then the catalog holds 2 Announcements

  Scenario: The Announcement holds no channel, no account, no words and no approval
    When the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval |
      | email   | site-one | hard     |
    Then the Announcement row has none of these fields
      | field         |
      | channel       |
      | accountId     |
      | approval      |
      | approvedBy    |
      | approvedAt    |
      | approvalPolicy|
      | text          |
      | textKey       |

  Scenario: A release time is stored in UTC and an empty one means as soon as allowed
    When the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-17T09:00:00-05:00" and these Deliveries
      | channel | account  | approval |
      | email   | site-one | none     |
    Then the Announcement's release time is "2026-11-17T14:00:00Z"
    When the decision "story-published:tide-tables" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval |
      | email   | site-one | none     |
    Then the Announcement for "story-published:tide-tables" has the release time "2026-11-16T14:00:00Z"

  Scenario: A release time with no offset is refused, so a local time is never read as UTC
    When the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with a release time "2026-11-17T09:00:00" and these Deliveries
      | channel | account  | approval |
      | email   | site-one | none     |
    Then the call is refused saying "needs its offset"
    And the catalog holds 0 Announcements
