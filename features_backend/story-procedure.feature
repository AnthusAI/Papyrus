Feature: One definition of the Story procedure
  A Story moves through the newsroom in one ordered list of steps, defined once and read by the command line. Each step
  has a stage, a role, a command and a status: live, off or not built. A step is done, not done or unknown; unknown is
  honest, and a step with no record to read is never reported as done. A skipped step needs a recorded reason and an open
  required step blocks publishing (features_backend/story-checklist.feature); there are no new stages, and human review is
  never a stage. Between the copy edit and publishing sit the four review lenses, done by hand with a findings note. People
  and agents read the same list: papyrus stories next shows where a Story stands and what comes next, and every write
  reminds the writer.

  Scenario: Choosing is done once the Story is past the idea stage
    Given a Story at the "idea" stage
    When the procedure is assessed
    Then the procedure step "choose" is "not_done"
    Given a Story at the "assignment" stage
    When the procedure is assessed
    Then the procedure step "choose" is "done"

  Scenario: Direction is done when an Assignment on the Story has a direction
    Given a Story at the "assignment" stage
    When the procedure is assessed
    Then the procedure step "direction" is "not_done"
    Given an Assignment on the Story with a direction
    When the procedure is assessed
    Then the procedure step "direction" is "done"

  Scenario: Direction also counts as done when the Assignment has instructions
    Given a Story at the "assignment" stage
    And an Assignment on the Story with instructions but no direction
    When the procedure is assessed
    Then the procedure step "direction" is "done"

  Scenario: Research is done when an Assignment on the Story has a research packet
    Given a Story at the "reporting" stage
    And an Assignment on the Story with a direction
    When the procedure is assessed
    Then the procedure step "research" is "not_done"
    Given the Assignment has a research packet
    When the procedure is assessed
    Then the procedure step "research" is "done"

  Scenario: The outline is done when the Story carries the outline marker
    Given a Story at the "reporting" stage
    When the procedure is assessed
    Then the procedure step "outline" is "not_done"
    Given the current version is number 2 and the outline marker is on version 2
    When the procedure is assessed
    Then the procedure step "outline" is "done"

  Scenario: The draft is a version newer than the outline
    Given a Story at the "copywriting" stage
    And the current version is number 2 and the outline marker is on version 2
    When the procedure is assessed
    Then the procedure step "draft" is "not_done"
    Given the current version is number 3 and the outline marker is on version 2
    When the procedure is assessed
    Then the procedure step "draft" is "done"

  Scenario: With no outline, a body at copywriting or later counts as the draft
    Given a Story at the "copywriting" stage
    And the current body is "A draft."
    When the procedure is assessed
    Then the procedure step "draft" is "done"
    Given a Story at the "reporting" stage
    And the current body is "Notes."
    When the procedure is assessed
    Then the procedure step "draft" is "not_done"

  Scenario: Copy-edit is done when the current version has a finished check without an error-level violation
    Given a Story at the "copywriting" stage
    When the procedure is assessed
    Then the procedure step "copy_edit" is "not_done"
    Given a finished check of the current version with no violation
    When the procedure is assessed
    Then the procedure step "copy_edit" is "done"
    Given a finished check of the current version with an error-level violation
    When the procedure is assessed
    Then the procedure step "copy_edit" is "not_done"
    Given a check of the current version whose lanes have not finished
    When the procedure is assessed
    Then the procedure step "copy_edit" is "not_done"

  Scenario: A warning-level violation does not block copy-edit
    Given a Story at the "copywriting" stage
    And a finished check of the current version with a warning-level violation
    When the procedure is assessed
    Then the procedure step "copy_edit" is "done"

  Scenario: Copy-edit is unknown when the check record cannot be read
    Given a Story at the "copywriting" stage
    And the check record cannot be read
    When the procedure is assessed
    Then the procedure step "copy_edit" is "unknown"

  Scenario: Editor review is done only for the current version and only when it approves
    Given a Story at the "copywriting" stage
    When the procedure is assessed
    Then the procedure step "editor_review" is "not_done"
    Given an editor review of the current version with the verdict "approve"
    When the procedure is assessed
    Then the procedure step "editor_review" is "done"
    Given an editor review of an earlier version with the verdict "approve"
    When the procedure is assessed
    Then the procedure step "editor_review" is "not_done"
    Given an editor review of the current version with the verdict "revise"
    When the procedure is assessed
    Then the procedure step "editor_review" is "not_done"

  Scenario: Editor review is off and says so
    Given a Story at the "copywriting" stage
    When the procedure is assessed
    Then the procedure step "editor_review" has the status "off"

  Scenario: Publishing is done when the Story is published
    Given a Story at the "typesetting" stage
    When the procedure is assessed
    Then the procedure step "publish" is "not_done"
    Given a Story at the "published" stage
    When the procedure is assessed
    Then the procedure step "publish" is "done"

  Scenario: A step that is not built is unknown and never done
    Given a Story at the "published" stage
    When the procedure is assessed
    Then the procedure step "fact_check" is "unknown"
    And the procedure step "illustration" is "unknown"
    And the procedure step "typesetting" is "unknown"
    And the procedure step "fact_check" has the status "not_built"

  Scenario: Next is the first live step that is not done
    Given a Story at the "reporting" stage
    And an Assignment on the Story with a direction
    And the Assignment has a research packet
    When the procedure is assessed
    Then the next step is "outline"

  Scenario: Next skips a step that is not built
    Given a Story at the "copywriting" stage
    And an Assignment on the Story with a direction
    And the Assignment has a research packet
    And the current version is number 3 and the outline marker is on version 2
    And a finished check of the current version with no violation
    When the procedure is assessed
    Then the next step is "review_people"

  Scenario: The four review lenses are live steps that no record proves
    Given a Story at the "copywriting" stage
    And a finished check of the current version with no violation
    When the procedure is assessed
    Then the procedure step "review_people" is "not_done"
    And the procedure step "review_reader_agents" is "not_done"
    And the procedure step "review_search" is "not_done"
    And the procedure step "review_social" is "not_done"
    And the procedure step "review_social" has the status "live"

  Scenario: A spiked or held Story has no next step
    Given a Story at the "spiked" stage
    When the procedure is assessed
    Then the Story has no next step
    Given a Story at the "held" stage
    When the procedure is assessed
    Then the Story has no next step

  Scenario: A Story created at copywriting shows the skipped steps
    Given a Story at the "copywriting" stage
    When I run "stories next" with "--story story-1"
    Then the procedure output has a line starting "skipped" for "direction"
    And the procedure output has a line starting "skipped" for "research"
    And the procedure output has a line starting "skipped" for "outline"
    And the procedure output has no line starting "skipped" for "fact_check"
    And the procedure output has no line starting "skipped" for "illustration"

  Scenario: Stories next prints every step with its state and then what comes next
    Given a Story at the "idea" stage
    When I run "stories next" with "--story story-1"
    Then the procedure output has a step line for each of the 17 steps
    And the procedure output has a "next" line for "choose"

  Scenario: A step that is off or not built says so instead of offering a command
    Given a Story at the "copywriting" stage
    And the current version is number 3 and the outline marker is on version 2
    When the next lines are written
    Then no next line offers a command for "fact_check"

  Scenario: Stories next writes nothing
    Given a Story at the "reporting" stage
    When I run "stories next" with "--story story-1"
    Then the procedure command wrote no records

  Scenario: Saving a version reminds the writer what comes next
    Given a Story at the "reporting" stage
    When I run "stories save-version" with "--story story-1 --body Hello --reason test --author-label AI --no-check"
    Then the procedure output has a "next" line
    And the new version was saved

  Scenario: A dry run prints no reminder and writes nothing
    Given a Story at the "reporting" stage
    When I run "stories save-version" with "--story story-1 --body Hello --reason test --author-label AI --no-check --dry-run"
    Then the procedure output has no "next" line
    And the procedure command wrote no records

  Scenario: A failure computing the reminder never fails the write
    Given a Story at the "reporting" stage
    And computing the reminder fails
    When I run "stories move" with "--story story-1 --stage copywriting"
    Then the procedure command succeeded
    And the Story is at the "copywriting" stage
    And one line about the reminder is written to the error output

  Scenario: Moving a Story to a later stage warns about skipped steps and still moves it
    Given a Story at the "idea" stage
    When I run "stories move" with "--story story-1 --stage copywriting"
    Then the procedure command succeeded
    And the Story is at the "copywriting" stage
    And the warning names the skipped step "direction"
    And the warning names the skipped step "research"
    And the warning names the skipped step "outline"

  Scenario: Moving a Story one stage along when nothing is skipped does not warn
    Given a Story at the "idea" stage
    When I run "stories move" with "--story story-1 --stage assignment"
    Then the procedure command succeeded
    And the procedure error output has no warning

  Scenario: A move reminder also prints after a move
    Given a Story at the "idea" stage
    When I run "stories move" with "--story story-1 --stage assignment"
    Then the procedure output has a "next" line for "direction"

  Scenario: Linking a reference reminds the writer
    Given a Story at the "reporting" stage
    And a Reference "ref-1" exists
    When I run "stories link-reference" with "--story story-1 --reference ref-1 --role consulted --author-label AI"
    Then the procedure output has a "next" line

  Scenario: Assigning research reminds the writer
    Given a Story at the "idea" stage
    When I run "stories assign-research" with "--story story-1 --direction Look-into-the-board"
    Then the procedure output has a "next" line for "research"

  Scenario: Creating a Story reminds the writer
    Given an empty newsroom
    When I run "stories create" with "--title Brand-new-Story"
    Then the procedure output has a "next" line for "choose"

  Scenario: Research on an Assignment that works on a Story reminds the writer
    Given a Story at the "assignment" stage
    And an Assignment on the Story with a direction
    When the research of that Assignment is reported
    Then the procedure output has a "next" line

  Scenario: The JSON result of research carries the next step
    Given a Story at the "assignment" stage
    And an Assignment on the Story with a direction
    When the research of that Assignment is reported as JSON
    Then the JSON result carries the next step

  Scenario: Research on an Assignment with no Story does not remind
    Given an Assignment with no Story
    When the research of that Assignment is reported
    Then the procedure output has no "next" line

  Scenario: Research that failed does not remind
    Given a Story at the "assignment" stage
    And an Assignment on the Story with a direction
    When the failed research of that Assignment is reported
    Then the procedure output has no "next" line

  Scenario: The outline flag records a marker and a later version counts as the draft
    Given a Story at the "reporting" stage
    When I run "stories save-version" with "--story story-1 --body Outline --reason outline --author-label AI --no-check --outline"
    Then the Story's current version carries the outline marker for version 2
    And the procedure step "draft" reads "not_done" for the Story
    When I run "stories save-version" with "--story story-1 --body Draft --reason draft --author-label AI --no-check"
    Then the procedure step "draft" reads "done" for the Story

  Scenario: A dry run of the outline flag writes no marker
    Given a Story at the "reporting" stage
    When I run "stories save-version" with "--story story-1 --body Outline --reason outline --author-label AI --no-check --outline --dry-run"
    Then the procedure command wrote no records

  Scenario: The documentation table lists every step
    Then every step key appears in the table of docs/story-procedure.md
