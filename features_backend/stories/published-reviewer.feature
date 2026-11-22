Feature: The person who reviewed a published version is on the published record, for the site to name
  When the lineage being published has a human review stamp for the version being published (`story_checklist.lineage_review_stamp`: the review of readers
  for a Story, `human_review` for a translation's own lineage), publishing puts `reviewedBy: {name, at}` on the published record, and the projection puts
  the same value on the entry's data (`entry.data["reviewedBy"]`), so a site's byline can name the reviewer. A delegated review is the person's: the
  record names the person the agent acted for, never the agent. No stamp, or a stamp of an earlier version, carries nothing. Only a person's public name
  is carried: a recorded label shaped like an email address is withheld, and then nothing is carried. The engine exposes the data; the site words it.
  Review is optional on some sites and required on others; either way a version that was reviewed carries its reviewer. Everything runs on the
  in-memory backend; nothing calls AWS or a model.

  Scenario: A person's review of the published version names that person
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    When I run "stories step" with "--story story-1 --step review_people --state done --note 'Read it through as a reader' --actor-label 'Ana Reviewer'"
    And the Story is published by an editor
    Then publishing succeeded
    And the published record of "story-1" names the reviewer "Ana Reviewer"
    And the page data of "story-1" names the reviewer "Ana Reviewer"

  Scenario: A delegated review names the person, not the agent
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    When I run "stories step" with "--story story-1 --step review_people --state done --note 'Ana read it on her phone' --agent Claude --on-instruction-of 'Ana Reviewer' --quote 'I read it, mark the review done'"
    And the Story is published by an editor
    Then publishing succeeded
    And the published record of "story-1" names the reviewer "Ana Reviewer"

  Scenario: A review ticked in the console names the signed-in person from their own profile, whatever name the request carries
    The content-actions function reads the person's name from their own newsroom profile, found by the token's subject; a name sent with the request is ignored.
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    And the signed-in editor's newsroom profile is named "Ana Reviewer"
    When the signed-in editor marks the review of readers done in the console, the request naming "Somebody Else"
    And the Story is published by an editor
    Then the checklist's review of readers is recorded under "Ana Reviewer"
    And the published record of "story-1" names the reviewer "Ana Reviewer"

  Scenario: A Story nobody reviewed carries no reviewer
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    When the Story is published by an editor
    Then the published record of "story-1" names no reviewer
    And the page data of "story-1" names no reviewer

  Scenario: A review of an earlier version carries no reviewer
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    When I run "stories step" with "--story story-1 --step review_people --state done --note 'Read it through' --actor-label 'Ana Reviewer'"
    And I run "stories save-version" with "--story story-1 --body 'A rewritten second paragraph' --reason edit --author-label Ryan --no-check"
    And the Story's newest version is published by an editor
    Then the published record of "story-1" names no reviewer

  Scenario: A recorded name shaped like an email address is never published
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    When I run "stories step" with "--story story-1 --step review_people --state done --note 'Read it through' --actor-label reviewer@example.com"
    And the Story is published by an editor
    Then the published record of "story-1" names no reviewer

  Scenario: A review recorded after the version went live is carried when it is published again, as the same version
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    When the Story is published by an editor
    And I run "stories step" with "--story story-1 --step review_people --state done --note 'Read it live' --actor-label 'Ana Reviewer'"
    And the Story is published by an editor
    Then the published record of "story-1" names the reviewer "Ana Reviewer"
    And the published record of "story-1" is published version 1

  Scenario: A translation's own review names its reviewer; the original's review does not
    Given the published English Story "story-waymo" version 3 in the Machines on Machines newsroom
    And a scripted translator, judge and repairer for "es-419"
    And an editor asked for the "es-419" translation of "story-waymo"
    And the English Story is served by a site that publishes Spanish under "es"
    And the translation run for "es-419" has finished
    When the agent "Claude" marks the translation's review done on the instruction of "Lucia" saying "Lo leí, está bien"
    And a person publishes the translation
    Then the published record of "story-waymo--es-419" names the reviewer "Lucia"
