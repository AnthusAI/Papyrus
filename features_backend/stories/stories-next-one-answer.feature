@checklist-gate
Feature: "papyrus stories next" gives one answer about what remains
  The Story's stored checklist is the record of what was done, so "papyrus stories next" reads every step's state from it.
  The records (the research packet, the outline, the draft, the copy-edit check) only add a hint where they differ; they never
  contradict a step's state. A review lens or the copy edit that was recorded done against an earlier version of the Story is
  shown as stale, with the version it was recorded against, and it still remains until it is recorded again for the current
  version. One list says what remains, and its count always agrees with the checklist progress.

  Scenario: Step rows agree with the stored items when the records cannot prove a manual step
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    And the review step "review_people" is done with the note "Read as a reader would."
    And the review step "review_reader_agents" is done with the note "Page reads cleanly as text."
    And the review step "review_search" is done with the note "Title and description fit."
    And the review step "review_social" is done with the note "Card title is clear."
    And the review step "concepts" is done with the note "Tagged: Surveillance."
    And the review step "related_content" is done with the note "Linked one story."
    When I run "stories next" with "--story story-1"
    Then the procedure output has a "step" line for "review_people" showing "done"
    And the procedure output has a "step" line for "review_social" showing "done"
    And the procedure output has a "step" line for "concepts" showing "done"
    And the procedure output has a "step" line for "related_content" showing "done"
    And every step line agrees with its item line
    And the procedure output has no "remaining" line for "review_people"
    And the procedure output has no "remaining" line for "concepts"
    And the procedure output has no "lens" line

  Scenario: What remains is one ordered list whose count agrees with the progress
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    And the review step "review_people" is done with the note "Read as a reader would."
    When I run "stories next" with "--story story-1"
    Then the procedure output has a "status" line reading "blocked"
    And the "remaining" lines are in order "direction, research, outline, copy_edit, review_reader_agents, review_search, review_social, concepts, related_content, illustration, publish"
    And the "status" line counts as many as there are "remaining" lines
    And the procedure output mentions "3/14"
    And the procedure output has a "next" line for "direction"

  Scenario: A review recorded against an earlier version is stale
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    And the review step "review_people" is done with the note "Read as a reader would."
    And a new version of the Story is saved
    When I run "stories next" with "--story story-1"
    Then the procedure output has a "step" line for "review_people" showing "stale"
    And the procedure output has a "version" line for "review_people" saying "STALE: recorded against v1, story is now v2"
    And the procedure output has a "remaining" line for "review_people"
    And the procedure output has a "lens" line for "review_people"
    And the procedure output has an "item" line for "review_people" showing "done"
    And the procedure output mentions "1 stale"

  Scenario: A skipped or not-applicable answer is not stale after a new version
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    And the checklist item "review_search" is marked "skipped" by the person "Ryan" with the reason "Not for search"
    And a new version of the Story is saved
    When I run "stories next" with "--story story-1"
    Then the procedure output has a "step" line for "review_search" showing "skipped"
    And the procedure output has a "version" line for "review_search" saying "current"
    And the procedure output has no "remaining" line for "review_search"

  Scenario: A copy edit recorded for an earlier version is stale until the check of the current version passes
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    And the checklist item "copy_edit" is marked "done" by the person "Ryan" with the reason "Checked v1"
    And a new version of the Story is saved
    When I run "stories next" with "--story story-1"
    Then the procedure output has a "step" line for "copy_edit" showing "stale"
    And the procedure output has a "version" line for "copy_edit" saying "STALE: recorded against v1, story is now v2"
    When a finished check of the current version with no violation passes
    And I run "stories next" with "--story story-1"
    Then the procedure output has a "step" line for "copy_edit" showing "done"
    And the procedure output has a "version" line for "copy_edit" saying "the records prove it for v2"
    And the procedure output has no "remaining" line for "copy_edit"

  Scenario: Recording the review again clears the stale mark
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    And the review step "review_people" is done with the note "Read as a reader would."
    And a new version of the Story is saved
    When I run "stories step" with "--story story-1 --step review_people --state done --note 'Read v2 again.' --actor-label Editor"
    And I run "stories next" with "--story story-1"
    Then the procedure output has a "step" line for "review_people" showing "done"
    And the procedure output has a "version" line for "review_people" saying "recorded against v2"
    And the procedure output has no "remaining" line for "review_people"

  Scenario: A review recorded before versions were tracked is placed by its time
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    And the review step "review_people" is done with the note "Read as a reader would."
    And the step "review_people" has no recorded version
    When I run "stories next" with "--story story-1"
    Then the procedure output has a "version" line for "review_people" saying "inferred from the time it was recorded"

  Scenario: Nothing remains when every step is done
    Given a Story at the "copywriting" stage
    And every step of the Story is closed
    When I run "stories next" with "--story story-1"
    Then the procedure output has a "status" line reading "complete"
    And the procedure output mentions "14/14"
    And the procedure output has no "remaining" line
    And the procedure output has no "next" line
    And the procedure output has no "lens" line

  Scenario: Only publishing is left
    Given a Story at the "copywriting" stage
    And every step of the Story is closed except publishing
    When I run "stories next" with "--story story-1"
    Then the procedure output has a "status" line reading "ready"
    And the "remaining" lines are in order "publish"

  Scenario: The records only hint when they differ from the checklist
    Given a Story at the "reporting" stage
    And an Assignment on the Story with a direction
    And the Story's checklist exists
    And the Assignment has a research packet
    When I run "stories next" with "--story story-1"
    Then the procedure output has a "step" line for "research" showing "not_done"
    And the procedure output has a "hint" line for "research"
    And the procedure output has a "remaining" line for "research"

  Scenario: The JSON answer carries the same status, remaining list and versions
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    And the review step "review_people" is done with the note "Read as a reader would."
    And a new version of the Story is saved
    When I run "stories next" with "--story story-1 --json"
    Then the JSON answer has the status "blocked" and lists "review_people" as stale
