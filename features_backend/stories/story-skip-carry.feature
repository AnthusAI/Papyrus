@checklist-gate
Feature: A skipped step keeps the version it was skipped for, and a later text edit reopens it
  A skip is an answer about one version of a Story. It records the version it was made for and the kind of change that version was against the one before
  it: text unchanged, picture only, or text edited. The skip stays on the checklist while the Story moves on, but a skip made on an earlier version is shown
  as "skipped on vN: <reason>", so its reason is never read as one about the current version. A later version that edits the text reopens the skipped steps
  whose answer reads the text (the copy edit, the four review lenses, a translation's review by a person); a change of picture only, of credit or alt text,
  keeps them skipped. A step that does not read the text (the outline) stays skipped whatever changes. A legacy bulk skip ("this edit only removes an
  AI-drafted disclaimer") is the case this guards: its reason was carried onto later edits that were not disclaimer removals.

  Scenario: A skip records the version it was made for and the kind of change that version was
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    And the Story is saved as version 2 with only its picture changed
    When I run "stories step" with "--story story-1 --step review_search --state skipped --reason 'Only the picture changed' --actor-label Ryan"
    Then the procedure command succeeded
    And the checklist item "review_search" was skipped on version 2 as "picture_only"

  Scenario: A skip on a version whose text did not change records that
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    And the Story is saved as version 2 with nothing changed
    When I run "stories step" with "--story story-1 --step review_people --state skipped --reason 'Republished with no change' --actor-label Ryan"
    Then the checklist item "review_people" was skipped on version 2 as "text_unchanged"

  Scenario: A skip carried onto a later version is shown with the version it was made for
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    And the Story is saved as version 2 with nothing changed
    And the checklist item "review_people" is marked "skipped" by the person "Ryan" with the reason "This edit only removes an AI-drafted disclaimer"
    And the Story is saved as version 3 with only its picture changed
    When the checklist is brought up to date after a change
    And I run "stories next" with "--story story-1"
    Then the procedure output mentions "skipped on v2 (text unchanged): This edit only removes an AI-drafted disclaimer"
    And the procedure output mentions "carried: skipped on v2"

  Scenario: A skip made on the current version is shown with its reason alone
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    And the checklist item "review_people" is marked "skipped" by the person "Ryan" with the reason "Short notice"
    When I run "stories next" with "--story story-1"
    Then the procedure output mentions "Short notice"
    And the procedure output does not mention "skipped on v1"

  Scenario: A later text edit reopens the skipped steps that read the text
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    And the checklist item "review_people" is marked "skipped" by the person "Ryan" with the reason "This edit only removes an AI-drafted disclaimer"
    And the checklist item "review_social" is marked "skipped" by the person "Ryan" with the reason "This edit only removes an AI-drafted disclaimer"
    And the Story is saved as version 2 with its text edited
    When the checklist is brought up to date after a change
    Then the checklist item "review_people" is "open"
    And the checklist item "review_social" is "open"
    And the checklist item "review_people" was changed by the system "Automatically, the text was edited after the skip"
    And the checklist item "review_people" has the note "Reopened: version 2 edits the text that the skip on version 1 was for (reason given then: This edit only removes an AI-drafted disclaimer)."
    When every required step except the review of readers is closed
    And the Story is published by an editor
    Then publishing was refused with the code "checklist-open" saying "Reviewed for readers (review_people)"

  Scenario: A picture-only edit keeps the skipped steps skipped
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    And the checklist item "review_people" is marked "skipped" by the person "Ryan" with the reason "Legacy Story, read before the checklist"
    And the Story is saved as version 2 with only its picture changed
    When the checklist is brought up to date after a change
    Then the checklist item "review_people" is "skipped"
    And the checklist item "review_people" has the reason "Legacy Story, read before the checklist"

  Scenario: A step that does not read the text stays skipped after a text edit
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    And the checklist item "outline" is marked "skipped" by the person "Ryan" with the reason "The editor wrote it by hand"
    And the Story is saved as version 2 with its text edited
    When the checklist is brought up to date after a change
    Then the checklist item "outline" is "skipped"

  Scenario: A translation's skipped review is reopened when a correction edits its text
    Given the published English Story "story-waymo" version 3 in the Machines on Machines newsroom
    And a scripted translator, judge and repairer for "es-419"
    And an editor asked for the "es-419" translation of "story-waymo"
    And the English Story is served by a site that publishes Spanish under "es"
    And the translation run for "es-419" has finished
    And a person skips the translation's review because "The Madrid editors read the draft"
    When a person named "Pat Editor" corrects "abarca" to "cubre" in the "es-419" translation because "the verb reads better"
    Then the translation's checklist item "human_review" is "open"
    When a person publishes the translation
    Then publishing is refused as "checklist-open" naming "human_review"
