@checklist-gate
Feature: The editorial checklist of a Story
  Every Story has one checklist, made from the Story procedure, so the newsroom can see which editorial steps happened,
  who did them, and why any were skipped. Following Kanbus, each live step of the procedure is a sub-task of the Story:
  an Item of type sub-task whose parent is the Story, in the same Item table as the Story, with a state: open, done,
  skipped or not applicable. Every change is a new version of that Item, so versions are the history. A skipped or not-applicable item needs a reason, a review item needs a findings note to be done,
  and only a person reopens an item. Evidence marks items done through the same logic that "papyrus stories next" uses,
  once, after a write. A template that gains a step gives an unpublished Story that step as open the next time the Story
  changes. Publishing refuses while a required item is open. The board reads a small summary kept on the Story, never
  the items, until a Story panel opens.

  Scenario: A new Story gets a checklist from the template
    Given an empty newsroom
    When I run "stories create" with "--title Brand-new-Story"
    Then the procedure command succeeded
    And the Story has 11 checklist items
    And the checklist item "choose" is "open"
    And the checklist item "review_people" is "open"
    And the checklist item "review_reader_agents" is "open"
    And the checklist item "review_search" is "open"
    And the checklist item "review_social" is "open"
    And the checklist item "publish" is "open"
    And every checklist item records template version 2

  Scenario: Steps that are off or not built have no item
    Given an empty newsroom
    When I run "stories create" with "--title Brand-new-Story"
    Then the checklist has no item for "fact_check"
    And the checklist has no item for "editor_review"
    And the checklist has no item for "illustration"
    And the checklist has no item for "typesetting"

  Scenario: A Story created past the idea stage starts with the choice made
    Given an empty newsroom
    When I run "stories create" with "--title Brand-new-Story --stage reporting"
    Then the checklist item "choose" is "done"
    And the checklist item "choose" was changed by the system "Automatically, from the Story's stage"

  Scenario: Skipping a step without a reason is refused
    Given a Story at the "reporting" stage
    And the Story's checklist exists
    When I run "stories step" with "--story story-1 --step outline --state skipped"
    Then the procedure command was refused saying "needs a reason"
    And the checklist item "outline" is "open"

  Scenario: Skipping a step with a reason records who and when
    Given a Story at the "reporting" stage
    And the Story's checklist exists
    When I run "stories step" with "--story story-1 --step outline --state skipped --reason 'The editor wrote it by hand' --actor-label Ryan"
    Then the procedure command succeeded
    And the checklist item "outline" is "skipped"
    And the checklist item "outline" has the reason "The editor wrote it by hand"
    And the checklist item "outline" was changed by the person "Ryan"
    And the checklist item "outline" records a change time

  Scenario: Not applicable also needs a reason
    Given a Story at the "reporting" stage
    And the Story's checklist exists
    When I run "stories step" with "--story story-1 --step direction --state not_applicable"
    Then the procedure command was refused saying "needs a reason"
    When I run "stories step" with "--story story-1 --step direction --state not_applicable --reason 'Started from a Reference'"
    Then the checklist item "direction" is "not_applicable"

  Scenario: A review step needs a findings note to be done
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    When I run "stories step" with "--story story-1 --step review_search --state done"
    Then the procedure command was refused saying "findings note"
    When I run "stories step" with "--story story-1 --step review_search --state done --note 'Title and description read well in results' --agent AI"
    Then the checklist item "review_search" is "done"
    And the checklist item "review_search" has the note "Title and description read well in results"
    And the checklist item "review_search" was changed by the agent "AI"

  Scenario: An unknown step is refused
    Given a Story at the "reporting" stage
    And the Story's checklist exists
    When I run "stories step" with "--story story-1 --step proofread --state done"
    Then the procedure command was refused saying "Unknown step"

  Scenario: Only a person reopens a step, and the history keeps every change
    Given a Story at the "reporting" stage
    And the Story's checklist exists
    And the checklist item "outline" is marked "skipped" by the person "Ryan" with the reason "Not needed"
    When an agent tries to reopen the step "outline"
    Then the procedure command was refused saying "Only a person reopens"
    And the checklist item "outline" is "skipped"
    When I run "stories step" with "--story story-1 --step outline --state open --actor-label Ryan"
    Then the checklist item "outline" is "open"
    And the checklist item "outline" has 3 history entries

  Scenario: A dry run changes nothing
    Given a Story at the "reporting" stage
    And the Story's checklist exists
    When I run "stories step" with "--story story-1 --step outline --state skipped --reason Later --dry-run"
    Then the procedure command wrote no records

  Scenario: A research packet marks the research step done with evidence
    Given a Story at the "reporting" stage
    And an Assignment on the Story with a direction
    And the Assignment has a research packet
    When the checklist is brought up to date after a change
    Then the checklist item "direction" is "done"
    And the checklist item "research" is "done"
    And the checklist item "research" was changed by the system "Automatically, from the research packet"
    And the checklist item "research" has evidence naming "a1"
    And the checklist item "outline" is "open"

  Scenario: Saving the outline and then the draft marks those steps done
    Given a Story at the "reporting" stage
    And the Story's checklist exists
    When I run "stories save-version" with "--story story-1 --body Outline --reason outline --author-label AI --no-check --outline"
    Then the checklist item "outline" is "done"
    And the checklist item "draft" is "open"
    When I run "stories save-version" with "--story story-1 --body Draft --reason draft --author-label AI --no-check"
    Then the checklist item "draft" is "done"
    And the checklist item "draft" has evidence naming "story-1-v3"

  Scenario: A passed copy-edit check marks the copy-edit step done
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    And a finished check of the current version with an error-level violation
    When the checklist is brought up to date after a change
    Then the checklist item "copy_edit" is "open"
    Given a finished check of the current version with no violation
    When the checklist is brought up to date after a change
    Then the checklist item "copy_edit" is "done"
    And the checklist item "copy_edit" has evidence naming "story-1-v1"

  Scenario: The four review lenses are never marked done by evidence
    Given a Story at the "copywriting" stage
    And a finished check of the current version with no violation
    When the checklist is brought up to date after a change
    Then the checklist item "review_people" is "open"
    And the checklist item "review_reader_agents" is "open"
    And the checklist item "review_search" is "open"
    And the checklist item "review_social" is "open"

  Scenario: A step a person reopened is not marked done again by evidence
    Given a Story at the "copywriting" stage
    And a finished check of the current version with no violation
    And the Story's checklist exists
    And the checklist item "copy_edit" is reopened by a person
    When the checklist is brought up to date after a change
    Then the checklist item "copy_edit" is "open"

  Scenario: A skipped step stays skipped when evidence appears later
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    And the checklist item "copy_edit" is marked "skipped" by the person "Ryan" with the reason "Checked by hand"
    And a finished check of the current version with no violation
    When the checklist is brought up to date after a change
    Then the checklist item "copy_edit" is "skipped"

  Scenario: A step the template gained is added as open the next time an unpublished Story changes
    Given a Story at the "reporting" stage
    And the Story's checklist was made before the step "review_social" existed
    Then the checklist has no item for "review_social"
    When I run "stories move" with "--story story-1 --stage copywriting"
    Then the checklist item "review_social" is "open"

  Scenario: A published Story is not given steps the template gains later
    Given a Story at the "published" stage
    And the Story's checklist was made before the step "review_social" existed
    When the checklist is brought up to date after a change
    Then the checklist has no item for "review_social"

  Scenario: The Story carries a summary the board card reads
    Given a Story at the "reporting" stage
    And the Story's checklist exists
    When I run "stories step" with "--story story-1 --step outline --state skipped --reason 'Written by hand'"
    And I run "stories step" with "--story story-1 --step direction --state not_applicable --reason 'From a Reference'"
    Then the Story card progress reads "2/11 · 1 skipped"
    And the Story summary lists "research" among the required steps still open

  Scenario: Publishing is refused while a required step is open
    Given a Story at the "copywriting" stage
    When the Story is published by an editor
    Then publishing was refused saying "Publishing is blocked"
    And publishing was refused saying "Reviewed for readers"
    And publishing was refused saying "papyrus stories step --story story-1"

  Scenario: Publishing works once every required step is done, skipped with a reason or not applicable with a reason
    Given a Story at the "copywriting" stage
    And every required step is closed
    When the Story is published by an editor
    Then publishing succeeded
    And the checklist item "publish" is "done"

  Scenario: One open review lens blocks publishing
    Given a Story at the "copywriting" stage
    And every required step is closed
    And the checklist item "review_social" is reopened by a person
    When the Story is published by an editor
    Then publishing was refused saying "Reviewed for social previews"

  Scenario: A Story made before the checklist existed gets one at publish time and is held to it
    Given a Story at the "copywriting" stage
    When the Story is published by an editor
    Then publishing was refused saying "Reviewed for readers"
    And the Story has 11 checklist items

  Scenario: Pages that are not Stories have no checklist and are not held
    Given a Story at the "copywriting" stage
    And the Story has the type "wiki_page"
    When the Story is published by an editor
    Then the Story has 0 checklist items

  Scenario: Stories next prints the stored checklist and its progress
    Given a Story at the "reporting" stage
    And the Story's checklist exists
    When I run "stories next" with "--story story-1"
    Then the procedure output has an "item" line for "choose" showing "done"
    And the procedure output has an "item" line for "outline" showing "open"
    And the procedure output mentions "1/11"

  Scenario: Stories next says so when a Story has no checklist yet and writes nothing
    Given a Story at the "reporting" stage
    When I run "stories next" with "--story story-1"
    Then the procedure output mentions "no checklist yet"
    And the procedure command wrote no records

  Scenario: The backfill with a dry run writes nothing and prints counts
    Given a Story at the "copywriting" stage
    When I run "stories checklist-backfill" with "--dry-run"
    Then the procedure command wrote no records
    And the procedure output mentions "stories 1"
    And the procedure output mentions "dry run"

  Scenario: The backfill gives an existing Story a checklist, marking steps done where evidence exists
    Given a Story at the "published" stage
    And a finished check of the current version with no violation
    When I run "stories checklist-backfill" with "--page-size 25"
    Then the procedure command succeeded
    And the checklist item "choose" is "done"
    And the checklist item "publish" is "done"
    And the checklist item "review_people" is "open"
    And the checklist item "review_social" is "open"
    And the procedure output mentions "stories 1"

  Scenario: Running the backfill again leaves finished checklists alone
    Given a Story at the "copywriting" stage
    When I run "stories checklist-backfill" with "--page-size 25"
    And I run "stories checklist-backfill" with "--page-size 25"
    Then the procedure output mentions "already_complete 1"
    And the procedure output mentions "created_items 0"

  Scenario: A step is a sub-task Item whose parent is its Story and whose versions are its history
    Given a Story at the "reporting" stage
    And the Story's checklist exists
    When I run "stories step" with "--story story-1 --step outline --state skipped --reason 'Written by hand' --actor-label Ryan"
    Then the checklist step "outline" is an Item of type "sub-task" with the parent "story-1"
    And the checklist step "outline" has 2 versions, the newest by "Ryan"
    And the sub-task Items have no stage, no section and no body

  Scenario: A sub-task is never published on its own and is never a Story
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    When the checklist step "outline" is published as an Item
    Then publishing was refused saying "never published on its own"
    And no page was published
    And the Story board lists only the Story, not its sub-tasks

  Scenario: An imported Story has every step but publishing marked not applicable, with the source as the reason
    Given a Story at the "copywriting" stage
    When the Story is imported from "articles/hello.md"
    Then the checklist item "review_people" is "not_applicable"
    And the checklist item "review_people" has the reason "imported from articles/hello.md"
    And the checklist item "review_people" was changed by the system "Automatically, from the import"
    And the checklist item "publish" is "open"
    When the Story is published by an editor
    Then publishing succeeded
