Feature: Human review of announcements is a setting of each publication
  Some publications run fully automatic: the first person to see an announcement is a reader. Others, such as Machines on Machines, release only what a person has
  reviewed. Both are normal, so review is data and not a rule. It is the announce responsibility's rung in the site's agent policy: hard is prepare (a person must release
  it), soft is publish with soft review (a person may edit or stop it before its lock time, and silence lets it go), and none is publish automatically. The publication has one
  value, and a channel, an Announcement kind or a newsletter list may override it; the narrowest wins and each override is optional. The value that applies is written to each
  Delivery as its approval, with where it came from and the version of the policy. A separate source rule, requireReviewedSource, is a condition on the input and not a rung:
  when it is on, an Announcement is made only for a Story a person has reviewed on its current version, and a Story edited after its review waits until a person reviews it
  again (PROVISIONAL: what counts as a person's review is defined in announcement-human-review-stamp.feature and Ryan has not confirmed it). Both are changed at any time and apply to Announcements made afterwards. Nothing here lowers the three-star floor or lets a machine supply a five.

  Background:
    Given an empty announcement catalog
    And the clock reads "2026-11-16T14:00:00Z"

  # --- the three values ---------------------------------------------------------------------------------------------------------------------------

  Scenario: Fully automatic: none everywhere and no review of the source
    Given a publication whose announcement review is "none"
    And the publication does not require a review before it announces
    And the Story "slow-water" at version 3 has 4 stars given by "ellie"
    When the announce agent announces the Story "slow-water" as "story_published" on these channels
      | channel | account  |
      | x       | handle-1 |
    Then an Announcement was made with 1 Deliveries
    And the Delivery "x" "handle-1" has the review "none" from "publication policy"
    And the Delivery "x" "handle-1" is approved by "system"
    And the Delivery "x" "handle-1" may go at "2026-11-16T14:00:00Z"
    And the Delivery "x" "handle-1" reads "Released automatically by publication policy" with the mark "bot"

  Scenario: Soft: a person may edit or stop it before the lock time, and silence lets it go
    Given a publication whose announcement review is "soft"
    And the Story "slow-water" at version 3 has 4 stars given by "ellie"
    When the announce agent announces the Story "slow-water" as "story_published" with a release time "2026-11-16T14:00:00Z" on these channels
      | channel  | account  | lock at              |
      | linkedin | page-one | 2026-11-16T14:20:00Z |
    Then the Delivery "linkedin" "page-one" has the review "soft" from "publication policy"
    And the Delivery "linkedin" "page-one" is not approved
    And the Delivery "linkedin" "page-one" may not go at "2026-11-16T14:10:00Z" because "waiting for review until the lock time"
    And the Delivery "linkedin" "page-one" may go at "2026-11-16T14:20:00Z"
    And the Delivery "linkedin" "page-one" reads "Goes at its lock time unless a person stops it" with the mark "hourglass"

  Scenario: Soft: a person who reads it earlier releases it before the lock time
    Given a publication whose announcement review is "soft"
    And the Story "slow-water" at version 3 has 4 stars given by "ellie"
    And the announce agent announces the Story "slow-water" as "story_published" with a release time "2026-11-16T14:00:00Z" on these channels
      | channel  | account  | lock at              |
      | linkedin | page-one | 2026-11-16T14:20:00Z |
    When the person "ellie" approves version 1 of the Delivery "linkedin" "page-one"
    Then the Delivery "linkedin" "page-one" may go at "2026-11-16T14:05:00Z"
    And the Delivery "linkedin" "page-one" reads "Released by a person (ellie)" with the mark "user-check"

  Scenario: Soft: a person who stops it before the lock time keeps it from going
    Given a publication whose announcement review is "soft"
    And the Story "slow-water" at version 3 has 4 stars given by "ellie"
    And the announce agent announces the Story "slow-water" as "story_published" with a release time "2026-11-16T14:00:00Z" on these channels
      | channel  | account  | lock at              |
      | linkedin | page-one | 2026-11-16T14:20:00Z |
    When the Announcement is stopped by a person before the lock time
    Then the Delivery "linkedin" "page-one" is withdrawn and cannot go at "2026-11-16T14:30:00Z"

  Scenario: Hard: it waits for a person however long it waits
    Given a publication whose announcement review is "hard"
    And the Story "slow-water" at version 3 has 4 stars given by "ellie"
    When the announce agent announces the Story "slow-water" as "story_published" on these channels
      | channel  | account  |
      | linkedin | page-one |
    Then the Delivery "linkedin" "page-one" has the review "hard" from "publication policy"
    And the Delivery "linkedin" "page-one" may not go at "2026-11-20T14:00:00Z" because "waiting for approval"
    And the Delivery "linkedin" "page-one" reads "Waits for a person to release it" with the mark "hand"
    When the person "ellie" approves version 1 of the Delivery "linkedin" "page-one"
    Then the Delivery "linkedin" "page-one" may go at "2026-11-20T14:00:00Z"

  Scenario: A publication whose announce agent prepares nothing gets no Delivery, and the list says why
    Given a publication whose announce agent is at the rung "draft"
    And the Story "slow-water" at version 3 has 4 stars given by "ellie"
    When the announce agent announces the Story "slow-water" as "story_published" on these channels
      | channel | account  |
      | x       | handle-1 |
    Then no Announcement was made
    And no Delivery was prepared for "x" because "announce is at draft"

  Scenario: A publication that has not set the announce review prepares nothing
    Given a publication with no announcement review set
    And the Story "slow-water" at version 3 has 4 stars given by "ellie"
    When the announce agent announces the Story "slow-water" as "story_published" on these channels
      | channel | account  |
      | x       | handle-1 |
    Then no Announcement was made
    And no Delivery was prepared for "x" because "the announce agent is off"

  # --- only reviewed Stories --------------------------------------------------------------------------------------------------------------------------

  Scenario: Reviewed only: a Story no person has reviewed creates no Announcement
    Given a publication whose announcement review is "soft"
    And the publication announces only Stories a person has reviewed
    And the Story "slow-water" at version 3 has 4 stars given by "ellie"
    When the announce agent announces the Story "slow-water" as "story_published" on these channels
      | channel | account  |
      | x       | handle-1 |
    Then nothing was announced because "has not been reviewed by a person"
    And the catalog holds 0 Deliveries

  Scenario: Reviewed only: once a person reviews the Story the same call makes the Announcement
    Given a publication whose announcement review is "soft"
    And the publication announces only Stories a person has reviewed
    And the Story "slow-water" at version 3 has 4 stars given by "ellie"
    And the announce agent announces the Story "slow-water" as "story_published" on these channels
      | channel | account  |
      | x       | handle-1 |
    When a person reviews version 3 of the Story "slow-water"
    And the announce agent announces the Story "slow-water" as "story_published" on these channels
      | channel | account  |
      | x       | handle-1 |
    Then an Announcement was made with 1 Deliveries
    And the catalog holds 1 Announcement

  Scenario: Reviewed only: a review of an earlier version does not count
    Given a publication whose announcement review is "soft"
    And the publication announces only Stories a person has reviewed
    And the Story "slow-water" at version 4 has 4 stars given by "ellie"
    And a person has reviewed version 3 of the Story "slow-water"
    When the announce agent announces the Story "slow-water" as "story_published" on these channels
      | channel | account  |
      | x       | handle-1 |
    Then nothing was announced because "slow-water version 4 has not been reviewed"

  Scenario: Reviewed only, roundups hard: a reviewed roundup waits for a person
    Given the publication starts from the settings of Machines on Machines
    And the Story "weekly-issue" at version 1 has 3 stars given by "ellie"
    And a person has reviewed version 1 of the Story "weekly-issue"
    When the announce agent announces the Stories "weekly-issue" as "roundup" under the key "roundup:weekly:2026-47" on these channels
      | channel | account |
      | email   | weekly  |
    Then the Delivery "email" "weekly" has the review "hard" from "override: kind roundup"
    And the Delivery "email" "weekly" may not go at "2026-11-20T14:00:00Z" because "waiting for approval"

  Scenario: Reviewed only: a Story edited after its review returns the Announcement to waiting
    Given the publication starts from the settings of Machines on Machines
    And the Story "slow-water" at version 3 has 4 stars given by "ellie"
    And a person has reviewed version 3 of the Story "slow-water"
    And the announce agent announces the Story "slow-water" as "story_published" on these channels
      | channel | account  |
      | x       | handle-1 |
    And the person "ellie" approves version 1 of the Delivery "x" "handle-1"
    When the Story "slow-water" is edited to version 4
    And the words of the drafted Deliveries are made again
    Then 0 Deliveries are ready again
    And "x" waits because "was changed after its review"
    And the Delivery "x" "handle-1" is waiting in the state "drafted"
    And the Delivery "x" "handle-1" may not go at "2026-11-20T14:00:00Z" because "the words are not ready"
    When a person reviews version 4 of the Story "slow-water"
    And the words of the drafted Deliveries are made again
    Then 1 Deliveries are ready again

  Scenario: Reviewed only and fully automatic: an edited Story does not go out unreviewed
    Given a publication whose announcement review is "none"
    And the publication announces only Stories a person has reviewed
    And the Story "slow-water" at version 3 has 4 stars given by "ellie"
    And a person has reviewed version 3 of the Story "slow-water"
    And the announce agent announces the Story "slow-water" as "story_published" on these channels
      | channel | account  |
      | x       | handle-1 |
    When the Story "slow-water" is edited to version 4
    And the words of the drafted Deliveries are made again
    Then 0 Deliveries are ready again
    And the Delivery "x" "handle-1" may not go at "2026-11-20T14:00:00Z" because "the words are not ready"

  # --- overrides: narrowest wins ----------------------------------------------------------------------------------------------------------------------

  Scenario: A channel override beats the publication
    Given a publication whose announcement review is "none"
    And the announcement review for the channel "linkedin" is "hard"
    And the Story "slow-water" at version 3 has 4 stars given by "ellie"
    When the announce agent announces the Story "slow-water" as "story_published" on these channels
      | channel  | account  |
      | linkedin | page-one |
      | x        | handle-1 |
    Then the Delivery "linkedin" "page-one" has the review "hard" from "override: channel linkedin"
    And the Delivery "x" "handle-1" has the review "none" from "publication policy"

  Scenario: A channel that needs a person waits while another channel with none goes
    Given a publication whose announcement review is "none"
    And the announcement review for the channel "linkedin" is "hard"
    And the Story "slow-water" at version 3 has 4 stars given by "ellie"
    When the announce agent announces the Story "slow-water" as "story_published" on these channels
      | channel  | account  |
      | linkedin | page-one |
      | x        | handle-1 |
    Then the Delivery "x" "handle-1" may go at "2026-11-16T14:00:00Z"
    And the Delivery "linkedin" "page-one" may not go at "2026-11-16T14:00:00Z" because "waiting for approval"
    And the catalog holds 1 Announcement

  Scenario: A kind override beats a channel override
    Given a publication whose announcement review is "soft"
    And the announcement review for the channel "linkedin" is "none"
    And the announcement review for the kind "roundup" is "hard"
    And the Story "weekly-issue" at version 1 has 3 stars given by "ellie"
    When the announce agent announces the Stories "weekly-issue" as "roundup" under the key "roundup:weekly:2026-47" on these channels
      | channel  | account  |
      | linkedin | page-one |
    Then the Delivery "linkedin" "page-one" has the review "hard" from "override: kind roundup"

  Scenario: A story post keeps its own value while roundups are hard
    Given a publication whose announcement review is "soft"
    And the announcement review for the kind "roundup" is "hard"
    And the announcement review for the kind "story_published" is "none"
    And the Story "slow-water" at version 3 has 4 stars given by "ellie"
    When the announce agent announces the Story "slow-water" as "story_published" on these channels
      | channel | account  |
      | x       | handle-1 |
    Then the Delivery "x" "handle-1" has the review "none" from "override: kind story_published"

  Scenario: The narrowest override wins when several match
    Given a publication whose announcement review is "none"
    And the announcement review for the channel "email" is "soft"
    And the announcement review for the kind "roundup" is "hard"
    And the announcement review where the kind is "roundup" and the channel is "email" is "soft"
    And the announcement review for the list "weekly" is "none"
    And the Story "weekly-issue" at version 1 has 3 stars given by "ellie"
    When the announce agent announces the Stories "weekly-issue" as "roundup" under the key "roundup:weekly:2026-47" on these channels
      | channel  | account | list   |
      | email    | weekly  | weekly |
      | email    | monthly | monthly |
      | linkedin | page    |        |
    Then the Delivery "email" "weekly" has the review "none" from "override: list weekly"
    And the Delivery "email" "monthly" has the review "soft" from "override: kind roundup, channel email"
    And the Delivery "linkedin" "page" has the review "hard" from "override: kind roundup"

  # --- changing it ------------------------------------------------------------------------------------------------------------------------------------

  Scenario: A change of the publication's review applies only to Announcements made afterwards
    Given a publication whose announcement review is "soft"
    And the Story "slow-water" at version 3 has 4 stars given by "ellie"
    And the Story "deep-time" at version 1 has 4 stars given by "ellie"
    And the announce agent announces the Story "slow-water" as "story_published" on these channels
      | channel | account  |
      | x       | handle-1 |
    When an admin changes the publication's announcement review to "hard" because "We want to read everything first"
    And the announce agent announces the Story "deep-time" as "story_published" on these channels
      | channel | account  |
      | x       | handle-2 |
    Then the Delivery "x" "handle-1" still has the review "soft" from "publication policy"
    And the Delivery "x" "handle-2" has the review "hard" from "publication policy"
    And the Delivery "x" "handle-2" records the version of the policy it was made under

  Scenario: An admin changes a kind and takes an override away
    Given a publication whose announcement review is "soft"
    And the announcement review for the channel "linkedin" is "hard"
    When an admin changes the announcement review for the kind "roundup" to "hard" because "Roundups wait for a person"
    Then the announcement review shows "soft" for the publication and "hard" for the kind "roundup"
    When an admin takes away the announcement review override for the channel "linkedin" because "LinkedIn follows the publication again"
    Then the announcement review for the channel "linkedin" and the kind "story_published" would be "soft" from "publication policy"

  Scenario: An editor changes the review of one planned Announcement and nothing else
    Given a publication whose announcement review is "none"
    And the Story "slow-water" at version 3 has 4 stars given by "ellie"
    And the announce agent announces the Story "slow-water" as "story_published" on these channels
      | channel  | account  |
      | linkedin | page-one |
      | x        | handle-1 |
    When an editor changes the review of the Delivery "linkedin" "page-one" to "hard"
    Then the Delivery "linkedin" "page-one" has the review "hard" from "set for this Delivery by ellie"
    And the Delivery "linkedin" "page-one" is not approved
    And the Delivery "linkedin" "page-one" may not go at "2026-11-16T14:00:00Z" because "waiting for approval"
    And the Delivery "x" "handle-1" still has the review "none" from "publication policy"
    And the announcement review for the channel "linkedin" and the kind "story_published" would be "none" from "publication policy"

  Scenario: An editor who lets one Delivery go automatically approves it as themselves
    Given a publication whose announcement review is "hard"
    And the Story "slow-water" at version 3 has 4 stars given by "ellie"
    And the announce agent announces the Story "slow-water" as "story_published" on these channels
      | channel | account  |
      | x       | handle-1 |
    When an editor changes the review of the Delivery "x" "handle-1" to "none"
    Then the Delivery "x" "handle-1" is approved by "ellie"
    And the Delivery "x" "handle-1" may go at "2026-11-16T14:00:00Z"

  Scenario: An editor cannot change the publication's review and an agent is blocked
    Given a publication whose announcement review is "soft"
    When an editor tries to change the publication's announcement review to "hard" because "I would like that"
    Then the change is refused as "not_authorized"
    And the policy has 1 versions

  Scenario: Fully automatic cannot be set while the floor that stops automatic publishing on doubt is missing
    Given a publication whose announcement review is "soft"
    When an admin tries to change the publication's announcement review to "none" because "Go fully automatic"
    Then the change is refused as "constraint_conflict"
    And the refusal says "hard floor"
    And the policy has 1 versions

  # --- what is recorded -------------------------------------------------------------------------------------------------------------------------------

  Scenario: Each Delivery records the review, where it came from and the policy version
    Given a publication whose announcement review is "soft"
    And the announcement review for the channel "linkedin" is "hard"
    And the Story "slow-water" at version 3 has 4 stars given by "ellie"
    When the announce agent announces the Story "slow-water" as "story_published" on these channels
      | channel  | account  |
      | linkedin | page-one |
      | x        | handle-1 |
    Then the Delivery "linkedin" "page-one" has the review "hard" from "override: channel linkedin"
    And the Delivery "linkedin" "page-one" records the version of the policy it was made under
    And the Delivery "x" "handle-1" has the review "soft" from "publication policy"
    And the Delivery "x" "handle-1" records the version of the policy it was made under

  # --- the defaults the ticket lists ------------------------------------------------------------------------------------------------------------------

  Scenario: A new publication starts soft and does not require a review of the source
    Given the publication starts from the settings of a new publication
    And the Story "slow-water" at version 3 has 4 stars given by "ellie"
    When the announce agent announces the Story "slow-water" as "story_published" on these channels
      | channel | account  |
      | x       | handle-1 |
    Then the Delivery "x" "handle-1" has the review "soft" from "publication policy"
    And the catalog holds 1 Announcement

  Scenario: Machines on Machines starts hard for roundups, soft for the rest, and reviewed only
    Given the publication starts from the settings of Machines on Machines
    And the Story "slow-water" at version 3 has 4 stars given by "ellie"
    When the announce agent announces the Story "slow-water" as "story_published" on these channels
      | channel | account  |
      | x       | handle-1 |
    Then nothing was announced because "has not been reviewed by a person"
    When a person reviews version 3 of the Story "slow-water"
    And the announce agent announces the Story "slow-water" as "story_published" on these channels
      | channel | account  |
      | x       | handle-1 |
    Then the Delivery "x" "handle-1" has the review "soft" from "publication policy"
