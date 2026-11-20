Feature: The announces and supersedes relation types
  Two relation types are seeded with the others. "announces" runs from an Announcement to a Story; "supersedes" runs from a Delivery to the Delivery it corrects.
  Each is a directional row with a deterministic id, so writing a link again changes nothing, and each is read through the relation indexes.

  Scenario: Both types are seeded with their ends
    Then the relation type "announces" runs from "announcement" to "item"
    And the relation type "supersedes" runs from "delivery" to "delivery"
    And neither relation type is symmetric

  Scenario: Writing a link twice writes one row
    Given an empty announcement catalog
    And the clock reads "2026-11-16T14:00:00Z"
    When the Announcement "announcement-1" is linked to the Story "slow-water" at version 3 twice
    Then the catalog holds 1 link

  Scenario: Looking at a newer version updates the same link
    Given an empty announcement catalog
    And the clock reads "2026-11-16T14:00:00Z"
    When the Announcement "announcement-1" is linked to the Story "slow-water" at version 3 twice
    And the Announcement "announcement-1" is linked to the Story "slow-water" at version 5
    Then the catalog holds 1 link
    And the link of "announcement-1" to "slow-water" names version 5

  Scenario: A Story's Announcements are one query on the object-state index
    Given an empty announcement catalog
    And the clock reads "2026-11-16T14:00:00Z"
    When the Announcement "announcement-1" is linked to the Story "slow-water" at version 3 twice
    And the Announcements of the Story "slow-water" are read through the relation
    Then 1 query was made, on the index "semanticRelationsByObjectState"
