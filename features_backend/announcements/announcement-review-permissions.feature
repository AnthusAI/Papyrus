Feature: What an agent may do with an announcement is one table, answered by one gate
  The operation table names, for each announcement operation, the lowest rung of the site's agent policy at which an agent may call it, or says that only a person may. The one gate
  reads the announce rung for the channel and kind the agent is working on, so what an agent may do with a Delivery follows that Delivery's review: it may release under none,
  and it is told a person must under soft or hard. Drafting is allowed from draft; correcting needs prepare, and the corrected Delivery goes only as its own review says. An agent
  can never change or unpin a block a person pinned, and can never change the review policy, the budget or what a person alone sets. A person's own action is never limited by an
  agent's rung. Withdrawing a Delivery, which can delete a public post, is reachable from prepare; the operation itself then allows an agent only when every Story the
  Announcement is about was retired (announcements-withdraw.feature), and tells it a person must otherwise.

  Background:
    Given an empty announcement catalog

  Scenario Outline: An agent releasing a Delivery gets the answer its channel's review gives
    Given a publication whose announcement review is "<publication>"
    And the announcement review for the channel "linkedin" is "<linkedin>"
    And an announce agent working on the channel "<channel>" for the kind "story_published"
    When the announce agent asks to "announcements_release"
    Then the announcement gate answers "<answer>"

    Examples:
      | publication | linkedin | channel  | answer         |
      | none        | hard     | x        | allowed        |
      | none        | hard     | linkedin | human_required |
      | soft        | none     | x        | human_required |
      | hard        | none     | x        | human_required |

  Scenario: An agent asking to release under hard is told a person must, and nothing is released
    Given a publication whose announcement review is "hard"
    And an announce agent working on the channel "x" for the kind "story_published"
    When the announce agent asks to "announcements_release"
    Then the announcement gate answers "human_required"
    And the agent's call did not write

  Scenario: An agent releasing under none is allowed because the policy did it
    Given a publication whose announcement review is "none"
    And an announce agent working on the channel "x" for the kind "story_published"
    When the announce agent asks to "announcements_release"
    Then the announcement gate answers "allowed"
    And the call wrote once

  Scenario: A person releases under any review
    Given a publication whose announcement review is "hard"
    When a person asks to "announcements_release"
    Then the announcement gate answers "allowed"
    And the call wrote once

  Scenario Outline: An agent drafts from the draft rung and corrects from prepare
    Given a publication whose announce agent is at the rung "<rung>"
    And an announce agent working on the channel "x" for the kind "story_published"
    When the announce agent asks to "<operation>"
    Then the announcement gate answers "<answer>"

    Examples:
      | rung         | operation            | answer         |
      | propose      | announcements_draft  | human_required |
      | draft        | announcements_draft  | allowed        |
      | draft        | announcements_correct | human_required |
      | prepare      | announcements_correct | allowed        |
      | publish_soft | announcements_correct | allowed        |

  Scenario Outline: An agent is told a person must unlock, at every rung
    Given a publication whose announce agent is at the rung "<rung>"
    And an announce agent working on the channel "x" for the kind "story_published"
    When the announce agent asks to "<operation>"
    Then the announcement gate answers "human_required"
    And the agent's call did not write

    Examples:
      | rung         | operation              |
      | prepare      | announcements_unlock   |
      | publish_auto | announcements_unlock   |

  Scenario Outline: An agent reaches withdraw from prepare, and the operation itself allows it only for a retired Story
    Given a publication whose announce agent is at the rung "<rung>"
    And an announce agent working on the channel "x" for the kind "story_published"
    When the announce agent asks to "announcements_withdraw"
    Then the announcement gate answers "<answer>"

    Examples:
      | rung         | answer         |
      | draft        | human_required |
      | prepare      | allowed        |
      | publish_auto | allowed        |

  Scenario Outline: An agent can never change a pinned block, the review policy or the budget
    Given a publication whose announce agent is at the rung "<rung>"
    And an announce agent working on the channel "x" for the kind "story_published"
    When the announce agent asks to "<operation>"
    Then the announcement gate answers "blocked"
    And the agent's call did not write

    Examples:
      | rung         | operation                    |
      | prepare      | announcements_pinned_change  |
      | publish_auto | announcements_pinned_change  |
      | prepare      | announcements_review_set     |
      | publish_auto | announcements_review_set     |
      | prepare      | announcements_settings_set   |
      | publish_auto | announcements_settings_set   |

  Scenario: An agent may not choose how much review one Delivery gets
    Given a publication whose announce agent is at the rung "publish_auto"
    And an announce agent working on the channel "x" for the kind "story_published"
    When the announce agent asks to "announcements_delivery_review_set"
    Then the announcement gate answers "human_required"
    And the agent's call did not write

  Scenario: A person asks for each of the operations the agent could not
    Given a publication whose announce agent is at the rung "off"
    When a person asks to "announcements_pinned_change"
    Then the announcement gate answers "allowed"
    And the call wrote once

  Scenario Outline: The table names the rung each operation needs
    Then the table names "<operation>" as needing "<rung>" from an agent

    Examples:
      | operation                          | rung         |
      | announcements_draft                | draft        |
      | announcements_correct              | prepare      |
      | announcements_release              | publish_auto |
      | announcements_unlock               | person       |
      | announcements_withdraw             | prepare      |
      | announcements_pinned_change        | person       |
      | announcements_review_set           | person       |
      | announcements_delivery_review_set  | person       |
      | announcements_settings_set         | person       |

  Scenario: An agent in an admin's own session may set the review to hard on that person's instruction, and the record names both
    Given a publication with no announcement review set
    When an agent in ada's session sets the publication's announcement review to "hard" on the instruction of "ada" who said "make it work"
    Then the policy was saved by "ada via cli (Claude)" with a reason holding "entered by Claude on the instruction of ada"
    And the policy was saved by "ada via cli (Claude)" with a reason holding "make it work"

  Scenario: An agent may not set the review to soft, which is a rung above prepare
    Given a publication with no announcement review set
    When an agent in ada's session sets the publication's announcement review to "soft" on the instruction of "ada" who said "go further"
    Then the change is refused as "blocked"
    And the policy still has no announce rung

  Scenario: An agent may not name a person other than the one whose session it runs in
    Given a publication with no announcement review set
    When an agent in ada's session sets the publication's announcement review to "hard" on the instruction of "bea" who said "do it"
    Then the change is refused as "not_authorized"
    And the policy still has no announce rung

  Scenario: An agent in an editor's session cannot change the review on anyone's instruction
    Given a publication with no announcement review set
    When an agent in ellie's session sets the publication's announcement review to "hard" on the instruction of "ellie" who said "do it"
    Then the change is refused as "not_authorized"

  Scenario: An agent that names no one is blocked
    Given a publication with no announcement review set
    When an agent in ada's session sets the publication's announcement review to "hard" naming no one
    Then the change is refused as "blocked"
    And the policy still has no announce rung
