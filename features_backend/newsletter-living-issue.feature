Feature: The issue is a living Story
  The roundup issue is one document that sits open all week. A machine fills the section slots with entries; people write the subject, the intro, the outro, the
  headings and their own words for an entry, and pin what they care about. Each block has one owner, every change is a new version with its actor, and neither
  side overwrites the other. An admin approves exactly one version for a time, and any edit afterwards takes the issue back to draft.

  Scenario: An item arrives mid-week
    Given an open issue where an editor wrote the intro
    When an article reaches three stars and the inserter adds it
    Then the issue has the article as a machine entry added by the inserter with the reason
    And the intro and every human field are exactly as the editor left them

  Scenario: A human removes an item and the inserter runs again
    Given an open issue with two machine entries
    When an editor removes one with a reason
    And the inserter runs again with that article and a new one
    Then the removed article is not added back
    And the issue shows who removed it, when and why
    When the editor restores it
    Then the inserter may add it again

  Scenario: A reason is required to remove an entry
    Given an open issue with two machine entries
    When an editor tries to remove one without a reason
    Then the removal is refused

  Scenario: A human edits machine copy
    Given an open issue with two machine entries
    When an editor rewrites one entry's blurb
    Then the entry is pinned and keeps the editor's words

  Scenario: An agent and a human edit at the same time
    Given an open issue with two machine entries
    When an agent and an editor both start from the same version
    And the editor writes the intro and the agent adds an entry
    Then both changes are kept as two versions with two actors

  Scenario: Two people write the same field
    Given an open issue where an editor wrote the intro
    When a second person who started from the older version writes the intro
    Then the second writer is told and sees the newer text
    And nothing is overwritten

  Scenario: An agent cannot overwrite a person's words
    Given an open issue where an editor wrote the intro
    When an agent tries to improve the intro
    Then the agent is told to post a suggestion and the intro is unchanged

  Scenario: An item falls below three stars after insertion
    Given an open issue with a pinned entry
    When its rating falls to two stars
    Then the entry is removed as below the floor even though it is pinned
    And when it is rated three stars again the inserter adds it back with the editor's copy

  Scenario: Approval then edit returns to draft
    Given an admin approved the issue
    When an editor changes the intro
    Then the issue is back in draft with the note "edited after approval; approve again"
    And the issue is no longer ready to send
    And the inserter resumes

  Scenario: The inserter pauses while approved
    Given an admin approved the issue
    When the inserter runs with a new article
    Then the issue is unchanged

  Scenario: Only admins approve
    Given an open issue with two machine entries
    When an editor tries to approve
    Then the approval is refused

  Scenario: Empty issue
    Given an open issue with no entries
    When an admin tries to approve
    Then the approval is refused because the issue has no entries

  Scenario: Approved and unchanged is ready to send
    Given an admin approved the issue
    Then the issue is ready to send
