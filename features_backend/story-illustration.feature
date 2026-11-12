@checklist-gate
Feature: Illustration is a checklist step and a publish gate
  A Story that needs a cover must not publish without one. "Illustrate" is a live, required step of the Story procedure,
  so it is on every Story's checklist, counted in its progress, shown by "papyrus stories next" and by the newsroom panel,
  and checked when a Story publishes. It is closed by evidence, never by hand: the current version has a cover (front matter
  "image") that is a stored asset. No approval is required by default, and none on any site unless it opts in. When a person does
  approve a cover, the approval is metadata: the front matter coverImage record names who approved it (or who picked it, for a stock
  picture picked in the newsroom). It is never a visible credit: a generated cover has no credit line and a third-party picture keeps
  its own. A site can opt in to requiring a recorded approval and an "Approved by NAME" line with the setting
  illustrationRequireApprovalCredit, which is off unless the site sets it. Where the site requires dark figures, a figure cover
  also has a stored dark picture. The only other way to close the step is an exception: a person skips it, or marks it not
  applicable, with a reason. Which Story types need a cover is a site setting, and articles do by default. A Story published
  before the step existed is not marked as failing, but a revision of it cannot publish until the step is closed.

  Scenario: Illustration is on the checklist and counts in the progress
    Given a Story at the "reporting" stage
    And the Story's checklist exists
    When I run "stories next" with "--story story-1"
    Then the procedure output has an "item" line for "illustration" showing "open"
    And the procedure output has a "step" line for "illustration" showing "not_done"
    And the procedure output has a "remaining" line for "illustration"
    And the procedure output mentions "1/14"
    And the Story card progress reads "1/14"

  Scenario: The newsroom panel and the command line list the same step
    Given a Story at the "reporting" stage
    And the Story's checklist exists
    Then the stored step "illustration" is a sub-task the newsroom lists as "Illustrate" in position 13 of 14
    And the Story summary lists "illustration" among the required steps still open
    And every checklist item records template version 5

  Scenario: A stock cover that a person picked closes the step by itself
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    And the Story has a stock cover picked by "Ryan"
    When the checklist is brought up to date after a change
    Then the checklist item "illustration" is "done"
    And the checklist item "illustration" was changed by the system "Automatically, from the cover"
    And the checklist item "illustration" has evidence naming "picked by Ryan"

  Scenario: A figure cover that a person approved closes the step by itself
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    And the Story has a figure cover approved by "Sierra"
    When the checklist is brought up to date after a change
    Then the checklist item "illustration" is "done"
    And the checklist item "illustration" has evidence naming "approved by Sierra"

  Scenario: A cover with no approval of any kind closes the step and publishes by default
    Given a Story at the "copywriting" stage
    And the Story has a figure cover that nobody approved
    And every required step is closed
    When the Story is published by an editor
    Then publishing succeeded
    And the checklist item "illustration" is "done"
    And the cover shows no credit line and no approval text

  Scenario: A site that opts in refuses a cover with no recorded approval
    Given a Story at the "copywriting" stage
    And the site requires an approved cover
    And the Story's checklist exists
    And the Story has a figure cover with an "Approved by Sierra" line on its image but no approval in metadata
    And every required step except Illustration is closed
    When the Story is published by an editor
    Then publishing was refused saying "illustrationRequireApprovalCredit"
    And publishing was refused saying "approvedBy"

  Scenario: A site that opts in refuses a recorded approval with no "Approved by" line
    Given a Story at the "copywriting" stage
    And the site requires an approved cover
    And the Story's checklist exists
    And the Story has a figure cover approved by "Sierra"
    And every required step except Illustration is closed
    When the Story is published by an editor
    Then publishing was refused saying "Approved by Sierra"

  Scenario: A site that opts in publishes once approval is recorded and its line is on the image
    Given a Story at the "copywriting" stage
    And the site requires an approved cover
    And the Story has a figure cover approved by "Sierra" and an "Approved by" line on its image
    And every required step is closed
    When the Story is published by an editor
    Then publishing succeeded
    And the checklist item "illustration" is "done"

  Scenario: A third-party picture keeps its credit and needs no approval line by default
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    And the Story has a stock cover picked by "Ryan"
    When the checklist is brought up to date after a change
    Then the checklist item "illustration" is "done"
    And the cover keeps its third-party credit line

  Scenario Outline: A cover without proof leaves the step open
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    And <cover>
    When the checklist is brought up to date after a change
    Then the checklist item "illustration" is "open"

    Examples:
      | cover                                       |
      | the Story has a cover that is not a stored asset |
      | the Story has a remote cover address        |

  Scenario: The step cannot be marked done by hand
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    When I run "stories step" with "--story story-1 --step illustration --state done --note 'It looks fine'"
    Then the procedure command was refused saying "cannot be marked done by hand"
    And the procedure command was refused saying "papyrus stories step --story story-1 --step illustration --state skipped --reason"
    And the checklist item "illustration" is "open"

  Scenario: Marking the step done is accepted when the records prove the cover
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    And the Story has a stock cover picked by "Ryan"
    When I run "stories step" with "--story story-1 --step illustration --state done"
    Then the procedure command succeeded
    And the checklist item "illustration" is "done"
    And the checklist item "illustration" has evidence naming "picked by Ryan"

  Scenario: A person records an exception with a reason
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    When I run "stories step" with "--story story-1 --step illustration --state skipped --reason 'A data table needs no picture'"
    Then the procedure command succeeded
    And the checklist item "illustration" is "skipped"
    And the checklist item "illustration" has the reason "A data table needs no picture"

  Scenario: An exception without a reason is refused
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    When I run "stories step" with "--story story-1 --step illustration --state skipped"
    Then the procedure command was refused saying "needs a reason"
    And the checklist item "illustration" is "open"

  Scenario: An agent cannot record the exception
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    When an agent marks the step "illustration" skipped with the reason "No time"
    Then the procedure command was refused saying "Only a person records an exception for Illustration"
    And the checklist item "illustration" is "open"

  Scenario: First publication is refused without a cover and says how to resolve it
    Given a Story at the "copywriting" stage
    And every required step except Illustration is closed
    When the Story is published by an editor
    Then publishing was refused saying "Illustrate (illustration)"
    And publishing was refused saying "the Story has no cover picture"
    And publishing was refused saying "papyrus stories save-version --story story-1"
    And publishing was refused saying "papyrus stories step --story story-1 --step illustration --state skipped --reason"

  Scenario: First publication works with an approved cover
    Given a Story at the "copywriting" stage
    And the Story has a stock cover picked by "Ryan"
    And every required step is closed
    When the Story is published by an editor
    Then publishing succeeded
    And the checklist item "illustration" is "done"

  Scenario: A cover added after the last checklist update still lets the Story publish
    Given a Story at the "copywriting" stage
    And every required step except Illustration is closed
    And the Story has a stock cover picked by "Ryan"
    When the Story is published by an editor
    Then publishing succeeded

  Scenario: First publication works with a person's exception
    Given a Story at the "copywriting" stage
    And every required step except Illustration is closed
    And the Story's checklist exists
    When a person marks the step "illustration" skipped with the reason "The piece is a plain list"
    And the Story is published by an editor
    Then publishing succeeded

  Scenario: A cover that was taken off after the step was done reads stale and blocks publishing
    Given a Story at the "copywriting" stage
    And the Story has a stock cover picked by "Ryan"
    And the Story's checklist exists
    And the cover is taken off the Story in a new version
    When I run "stories next" with "--story story-1"
    Then the procedure output has a "step" line for "illustration" showing "stale"
    And the procedure output has a "remaining" line for "illustration"
    When the Story is published by an editor
    Then publishing was refused saying "the Story has no cover picture"

  Scenario: Where the site requires dark figures, a figure cover with no dark picture is not enough
    Given a Story at the "copywriting" stage
    And the site requires dark figures
    And the Story's checklist exists
    And the Story has a figure cover approved by "Sierra"
    And every required step except Illustration is closed
    When the Story is published by an editor
    Then publishing was refused saying "has no dark picture"
    And publishing was refused saying "requireDarkFigures"
    And the checklist item "illustration" is "open"

  Scenario: Where the site requires dark figures, a figure cover with a stored dark picture is enough
    Given a Story at the "copywriting" stage
    And the site requires dark figures
    And the Story's checklist exists
    And the Story has a figure cover approved by "Sierra" with a dark picture
    When the checklist is brought up to date after a change
    Then the checklist item "illustration" is "done"
    And the checklist item "illustration" has evidence naming "dark"

  Scenario: A new version saved with only a body change keeps both pictures of a figure cover
    Given a Story at the "copywriting" stage
    And the site requires dark figures
    And the Story's checklist exists
    And the Story has a figure cover approved by "Sierra" with a dark picture
    When an editor saves a new version that changes only the body
    Then the new version stores both the cover and its dark picture
    When the checklist is brought up to date after a change
    Then the checklist item "illustration" is "done"
    And the checklist item "illustration" has evidence naming "dark"

  Scenario: A stock photograph is never asked for a dark picture
    Given a Story at the "copywriting" stage
    And the site requires dark figures
    And the Story's checklist exists
    And the Story has a stock cover picked by "Ryan"
    When the checklist is brought up to date after a change
    Then the checklist item "illustration" is "done"

  Scenario: A Story type the site does not list has no Illustration item and is not held to it
    Given a Story at the "copywriting" stage
    And the Story has the type "post"
    And the Story's checklist exists
    Then the checklist has no item for "illustration"
    When I run "stories next" with "--story story-1"
    Then the procedure output has a "step" line for "illustration" showing "not_applicable"
    And the procedure output has no "remaining" line for "illustration"
    When the Story is published by an editor
    Then publishing was refused saying "Reviewed for readers"
    And publishing was refused saying "papyrus stories step"

  Scenario: A site can require a cover for another Story type
    Given a Story at the "copywriting" stage
    And the site requires a cover for "post" Stories
    And the Story has the type "post"
    And the Story's checklist exists
    Then the checklist item "illustration" is "open"

  Scenario: A Story published before the step existed is not marked as failing
    Given a Story at the "published" stage
    And the Story's checklist exists
    When I run "stories next" with "--story story-1"
    Then the checklist has no item for "illustration"
    And the procedure output has no "remaining" line for "illustration"

  Scenario: The backfill leaves a published Story without an Illustration item
    Given a Story at the "published" stage
    When I run "stories checklist-backfill" with "--page-size 50"
    Then the procedure command succeeded
    And the checklist has no item for "illustration"

  Scenario: An existing draft gets the step when its checklist is brought up to date
    Given a Story at the "copywriting" stage
    And the Story's checklist was made before the step "illustration" existed
    And the Story has a stock cover picked by "Ryan"
    When I run "stories checklist-backfill" with "--page-size 50"
    Then the checklist item "illustration" is "done"
    And the checklist item "illustration" was changed by the system "Automatically, from the cover"

  Scenario: An existing draft with no cover gets the step open
    Given a Story at the "copywriting" stage
    And the Story's checklist was made before the step "illustration" existed
    When the checklist is brought up to date after a change
    Then the checklist item "illustration" is "open"

  Scenario: A revision of a Story published before the step existed is refused until the step is closed
    Given a Story at the "published" stage
    And the Story's checklist exists
    And a revision of the published Story is saved at the "copywriting" stage
    And every required step except Illustration is closed
    When the Story is published by an editor
    Then publishing was refused saying "Illustrate (illustration)"
    And publishing was refused saying "papyrus stories step --story story-1 --step illustration --state skipped --reason"

  Scenario: That revision publishes once a cover is added
    Given a Story at the "published" stage
    And the Story's checklist exists
    And a revision of the published Story is saved at the "copywriting" stage
    And the Story has a stock cover picked by "Ryan"
    And every required step is closed
    When the Story is published by an editor
    Then publishing succeeded

  Scenario: That revision publishes once a person records an exception
    Given a Story at the "published" stage
    And the Story's checklist exists
    And a revision of the published Story is saved at the "copywriting" stage
    And every required step except Illustration is closed
    And the Story's checklist exists
    When a person marks the step "illustration" skipped with the reason "Revised for a typo only"
    And the Story is published by an editor
    Then publishing succeeded

  Scenario: Republishing a published Story that kept its stage is held to the step as well
    Given a Story at the "published" stage
    And the Story's checklist exists
    And every required step except Illustration is closed
    When the Story is published by an editor
    Then publishing was refused saying "Illustrate (illustration)"
    When a person marks the step "illustration" skipped with the reason "Republished for a typo only"
    And the Story is published by an editor
    Then publishing succeeded
