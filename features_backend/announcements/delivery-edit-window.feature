Feature: A Delivery is a draft with an edit window, and every edit is a new saved version
  The machine drafts the words of a Delivery and people edit them before they go out. The window runs from the Delivery's creation to its release time, and how long it is
  belongs to the kind of Announcement and the channel: a weekly newsletter has a week, a story post may have twenty minutes. Those lengths are data in the announcement
  settings, never code, and a Delivery made without one is released as soon as it is allowed.

  Every edit is a new version of the Delivery's words and no version is overwritten. The words of each version are a file in S3; the row holds only the key and hash of
  each, who saved it, when, and which version it replaced. A save names the version it replaces, so two people (or a person and a machine redraft) who read the same version
  never silently overwrite each other: the second is refused with an answer that names the version that replaced the one it read, and a machine redraft in that position is
  dropped because the person's version is newer.

  Background:
    Given an empty announcement catalog
    And the clock reads "2026-11-16T14:00:00Z"
    And the Story "slow-water" is at version 3

  Scenario: A story post has twenty minutes and locks five minutes before it goes
    Given the site's edit windows are
      | kind            | channel | window minutes | lock lead minutes |
      | story_published | x       | 20             | 5                 |
    When the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" under the site's edit windows with these Deliveries
      | channel | account  | approval | text                  |
      | x       | handle-1 | soft     | Slow water is on shelves |
    Then the Delivery row "x" "handle-1" holds
      | field     | value                |
      | releaseAt | 2026-11-16T14:20:00Z |
      | lockAt    | 2026-11-16T14:15:00Z |
    And the Announcement for "story-published:slow-water" has the release time "2026-11-16T14:20:00Z"
    And the Delivery "x" "handle-1" is due at "2026-11-16T14:15:00Z"

  Scenario: A weekly newsletter has a week, whatever the story post has
    Given the site's edit windows are
      | kind            | channel | window minutes | lock lead minutes |
      | story_published | x       | 20             | 5                 |
      | roundup         | email   | 10080          | 120               |
    When the decision "roundup:weekly:2026-w46" of kind "roundup" is made for the Story "slow-water" under the site's edit windows with these Deliveries
      | channel | account  | approval | text              |
      | email   | site-one | hard     | This week's issue |
    Then the Delivery row "email" "site-one" holds
      | field     | value                |
      | releaseAt | 2026-11-23T14:00:00Z |
      | lockAt    | 2026-11-23T12:00:00Z |

  Scenario: A roundup that already has its scheduled time keeps it and locks before it
    Given the site's edit windows are
      | kind    | channel | window minutes | lock lead minutes |
      | roundup | email   | 10080          | 120               |
    When the decision "roundup:weekly:2026-w47" of kind "roundup" is made for the Story "slow-water" under the site's edit windows with the release time "2026-11-20T09:00:00Z" and these Deliveries
      | channel | account  | approval | text              |
      | email   | site-one | hard     | This week's issue |
    Then the Delivery row "email" "site-one" holds
      | field     | value                |
      | releaseAt | 2026-11-20T09:00:00Z |
      | lockAt    | 2026-11-20T07:00:00Z |

  Scenario: The length of a window is data: changing it changes the next Delivery and no code
    Given the site's edit windows are
      | kind            | channel | window minutes | lock lead minutes |
      | story_published | x       | 20             | 5                 |
    When the site's edit windows are changed to
      | kind            | channel | window minutes | lock lead minutes |
      | story_published | x       | 45             | 10                |
    And the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" under the site's edit windows with these Deliveries
      | channel | account  | approval | text       |
      | x       | handle-1 | soft     | Slow water |
    Then the Delivery row "x" "handle-1" holds
      | field     | value                |
      | releaseAt | 2026-11-16T14:45:00Z |
      | lockAt    | 2026-11-16T14:35:00Z |
    And the site's announcement settings keep the edit windows as data under "editWindows"

  Scenario: The narrowest window that fits wins
    Given the site's edit windows are
      | kind            | channel | window minutes | lock lead minutes |
      |                 |         | 60             | 0                 |
      |                 | x       | 30             | 5                 |
      | story_published |         | 20             | 4                 |
      | story_published | x       | 10             | 2                 |
    When the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" under the site's edit windows with these Deliveries
      | channel  | account  | approval | text                |
      | x        | handle-1 | soft     | On the narrow window |
      | linkedin | page-1   | soft     | On the kind's window |
    Then the Delivery row "x" "handle-1" holds
      | field     | value                |
      | releaseAt | 2026-11-16T14:10:00Z |
      | lockAt    | 2026-11-16T14:08:00Z |
    And the Delivery row "linkedin" "page-1" holds
      | field     | value                |
      | releaseAt | 2026-11-16T14:20:00Z |
      | lockAt    | 2026-11-16T14:16:00Z |

  Scenario: A kind and channel with no window are released as soon as they are allowed, with no separate lock
    Given the site has no edit windows
    When the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" under the site's edit windows with these Deliveries
      | channel | account  | approval | text       |
      | x       | handle-1 | none     | Slow water |
    Then the Delivery row "x" "handle-1" holds
      | field     | value                |
      | releaseAt | 2026-11-16T14:00:00Z |
      | lockAt    | 2026-11-16T14:00:00Z |

  Scenario: A lock that comes before the window opens, or a window that is not a number of minutes, is refused with the reason
    When the site's edit windows are saved as
      | kind            | channel | window minutes | lock lead minutes |
      | story_published | x       | 20             | 30                |
    Then the edit windows are refused saying "more than its 20 minute window"
    When the site's edit windows are saved as
      | kind            | channel | window minutes | lock lead minutes |
      | story_published | x       | 20             | 5                 |
      | story_published | x       | 40             | 5                 |
    Then the edit windows are refused saying "two edit windows for kind story_published, channel x"

  Scenario: Every edit is a new version and the earlier versions are kept
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval | text                 |
      | x       | handle-1 | soft     | The machine's draft. |
    When the person "ellie" saves version 1 of the Delivery "x" "handle-1" with the words "Ellie's rewrite."
    And the person "sierra" saves version 2 of the Delivery "x" "handle-1" with the words "Sierra's tighter rewrite."
    Then the Delivery "x" "handle-1" is at version 3
    And version 1 of the Delivery "x" "handle-1" has the words "The machine's draft."
    And version 2 of the Delivery "x" "handle-1" has the words "Ellie's rewrite."
    And version 3 of the Delivery "x" "handle-1" has the words "Sierra's tighter rewrite."
    And version 1 of the Delivery "x" "handle-1" is the first version, drafted by the machine
    And version 2 of the Delivery "x" "handle-1" was saved by "ellie" as human and replaced version 1
    And version 3 of the Delivery "x" "handle-1" was saved by "sierra" as human and replaced version 2
    And the Delivery "x" "handle-1" keeps 3 versions, each its own file in S3

  Scenario: The row holds the key and hash of each version and never the words
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval | text              |
      | x       | handle-1 | soft     | Plain words here. |
    When the person "ellie" saves version 1 of the Delivery "x" "handle-1" with the words "Other plain words there."
    Then the Delivery row "x" "handle-1" holds the key and hash of each version and none of "Other plain words"
    And the Delivery row "x" "handle-1" holds the key and hash of each version and none of "Plain words here"

  Scenario: Saving the words that are already there makes no version
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval | text             |
      | x       | handle-1 | soft     | Words that stay. |
    And the writes so far are remembered
    When the person "ellie" saves version 1 of the Delivery "x" "handle-1" with the words "Words that stay."
    Then the save made no new version
    And nothing more was written
    And the Delivery "x" "handle-1" is at version 1

  Scenario: Two saves against one version leave one winner, and the second is told which version replaced the one it read
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval | text               |
      | x       | handle-1 | soft     | The first draft.   |
    When the person "sierra" saves version 1 of the Delivery "x" "handle-1" with the words "Sierra's words." after "ellie" saved first
    Then the call is refused saying "Read it again"
    And the Delivery save is refused as stale
    And the refusal names version 2 saved by "ellie" as the one that replaced version 1
    And the call is refused saying "version 2, saved by ellie"
    And the Delivery "x" "handle-1" is at version 2
    And version 2 of the Delivery "x" "handle-1" has the words "Words from ellie"
    And the Delivery "x" "handle-1" keeps 2 versions, each its own file in S3

  Scenario: A stale save names the version that replaced the one read even when several came after it
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval | text             |
      | x       | handle-1 | soft     | The first draft. |
    And the person "ellie" saves version 1 of the Delivery "x" "handle-1" with the words "Second."
    And the person "ellie" saves version 2 of the Delivery "x" "handle-1" with the words "Third."
    When the person "sierra" saves version 1 of the Delivery "x" "handle-1" with the words "Too late."
    Then the Delivery save is refused as stale
    And the refusal names version 2 saved by "ellie" as the one that replaced version 1
    And the call is refused saying "is at version 3"

  Scenario: A machine redraft made against a stale version is dropped and the person's version stays
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval | text               |
      | x       | handle-1 | soft     | The machine draft. |
    And the person "ellie" saves version 1 of the Delivery "x" "handle-1" with the words "Ellie's version."
    And the writes so far are remembered
    When the machine redrafts version 1 of the Delivery "x" "handle-1" with the words "A fresh machine draft."
    Then the redraft was dropped and nothing was written
    And nothing more was written
    And the dropped redraft says "Read it again"
    And the Delivery "x" "handle-1" is at version 2
    And version 2 of the Delivery "x" "handle-1" has the words "Ellie's version."

  Scenario: A machine redraft of the version it read is saved as the machine's version
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval | text               |
      | x       | handle-1 | soft     | The machine draft. |
    When the machine redrafts version 1 of the Delivery "x" "handle-1" with the words "A better machine draft."
    Then the save was a saved version
    And version 2 of the Delivery "x" "handle-1" was saved by "announce" as machine and replaced version 1
    And version 1 of the Delivery "x" "handle-1" has the words "The machine draft."

  Scenario: A save whose file did not reach S3 is finished by the same call made again
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval | text             |
      | x       | handle-1 | soft     | The first draft. |
    And the next upload of a Delivery's words fails as if the connection dropped
    When the person "ellie" saves version 1 of the Delivery "x" "handle-1" with the words "Ellie's words."
    Then the call fails
    When the person "ellie" saves version 1 of the Delivery "x" "handle-1" with the words "Ellie's words."
    Then the call went through
    And the Delivery "x" "handle-1" is at version 2
    And version 2 of the Delivery "x" "handle-1" has the words "Ellie's words."
    And the Delivery "x" "handle-1" keeps 2 versions, each its own file in S3

  Scenario: Under none the policy approves each new version at once, as it does a Story's next version
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval | text             |
      | x       | handle-1 | none     | The first draft. |
    When the person "ellie" saves version 1 of the Delivery "x" "handle-1" with the words "Ellie's version."
    Then the Delivery "x" "handle-1" was approved by "system"
    And the Delivery row "x" "handle-1" holds
      | field           | value |
      | approvedVersion | 2     |

  Scenario: Under soft or hard an edited version is not approved until a person or the lock approves it
    Given the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel  | account  | approval | text             |
      | x        | handle-1 | hard     | The first draft. |
    And the person "ellie" approves version 1 of the Delivery "x" "handle-1"
    When the person "ellie" saves version 1 of the Delivery "x" "handle-1" with the words "Ellie's version."
    Then the Delivery "x" "handle-1" is not approved
