@checklist-gate
Feature: A site defines its own Story procedure
  The engine ships one default list of steps a Story goes through. A site may save its own procedure as a guideline document: the whole ordered list,
  ending with publishing, in which a built-in step keeps its checks and may change its words and whether it is optional, a built-in step that is left out
  is not part of the site's procedure, and a step the site adds is done by hand with a findings note. A Story's checklist, the reminders, the next step
  and the rule that publishing refuses while a required step is open all follow the site's list. A site that saves nothing gets the default list.

  Scenario: A site that saved no procedure gets the default list
    Given an empty newsroom
    And a site that saved no procedure
    When I run "stories create" with "--title Brand-new-Story"
    Then the procedure command succeeded
    And the Story has 14 checklist items

  Scenario: A site's procedure decides which steps the checklist has
    Given an empty newsroom
    And a site whose procedure is choose, draft, a step of its own "label_check" at the "copywriting" stage, and publish
    When I run "stories create" with "--title Brand-new-Story"
    Then the procedure command succeeded
    And the Story has 4 checklist items
    And the checklist item "label_check" is "open"
    And the checklist has no item for "review_people"

  Scenario: A step of the site's own needs a findings note to be done
    Given a Story at the "copywriting" stage
    And a site whose procedure is choose, draft, a step of its own "label_check" at the "copywriting" stage, and publish
    And the Story's checklist exists
    When I run "stories step" with "--story story-1 --step label_check --state done"
    Then the procedure command was refused saying "needs a short findings note"

  Scenario: Publishing refuses while a step of the site's own is open
    Given a Story at the "copywriting" stage
    And a site whose procedure is choose, draft, a step of its own "label_check" at the "copywriting" stage, and publish
    And the Story's checklist exists
    When the Story is published by an editor
    Then publishing was refused saying "label_check"

  Scenario: An optional step of the site's own does not block publishing
    Given a Story at the "copywriting" stage
    And a site whose procedure makes its own step "label_check" optional
    And the Story's checklist exists
    And every required step is closed
    When the Story is published by an editor
    Then publishing succeeded

  Scenario: A step the site left out cannot be marked
    Given a Story at the "copywriting" stage
    And a site whose procedure is choose, draft, a step of its own "label_check" at the "copywriting" stage, and publish
    And the Story's checklist exists
    When I run "stories step" with "--story story-1 --step review_people --state done --note found-nothing"
    Then the procedure command was refused saying "Unknown step"

  Scenario: A procedure that does not end with publishing is refused when saved
    Given an empty newsroom
    When an admin saves a procedure of choose and draft
    Then the procedure save is refused saying "must end with the publish step"

  Scenario: A built-in step cannot have its checks changed
    Given an empty newsroom
    When an admin saves a procedure that gives the built-in step "draft" a stage
    Then the procedure save is refused saying "cannot be changed on a built-in step"

  Scenario: A step of the site's own needs a title and a stage
    Given an empty newsroom
    When an admin saves a procedure with a step of its own that has no title
    Then the procedure save is refused saying "needs a title"
