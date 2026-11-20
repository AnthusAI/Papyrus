Feature: The Illustration lifecycle is data, and its step cannot close without alt text or a third-party credit
  A Story's Illustration step goes from needed to candidates made, chosen and placed. The stages, who moves each one and where a person is wanted are written as a file the
  illustrating agent loads. When the step runs unattended the agent makes one image; when a person is choosing it may make several. A generated image carries no credit and a
  third-party image is always credited. The step is closed by the records, never by hand: it stays open while the cover has no alt text that describes the picture, and it
  stays open while a third-party picture has no credit line. A Story that needs a picture and has none stays at the step, shown as open, and nothing removes it.

  Scenario: Each stage of the Illustration lifecycle names its mover
    Given the lifecycle of "Illustration"
    Then its stages are "Needed, Candidates made, Chosen, Placed"
    And every stage names a mover that is a responsibility in the catalog or the engine
    And the "Candidates made" stage is moved by "Illustrate"
    And the "Candidates made" stage asks no person

  Scenario: Unattended the agent makes one image, and a person choosing may be given several
    Given the lifecycle of "Illustration"
    Then the "Candidates made" stage's words say "Unattended, the agent makes one image"
    And the "Candidates made" stage's words say "When a person is choosing it may make several"
    And the "Candidates made" stage's words say "A request for a figure from another agent is an Assignment"

  Scenario: A person chooses the picture below the rung publish_soft
    Given the lifecycle of "Illustration"
    Then the "Chosen" stage asks a person below the rung "publish_soft"

  Scenario: A Story that needs a picture stays at the step and is counted
    Given the lifecycle of "Illustration"
    Then when nobody acts the "Needed" stage keeps the record and counts it
    And no stage removes a record for its age

  Scenario: A third-party picture with no credit keeps the step open
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    And the Story has a stock cover picked by "Ryan" whose image line has no credit
    When the checklist is brought up to date after a change
    Then the checklist item "illustration" is "open"
    When I run "stories step" with "--story story-1 --step illustration --state done --note 'It looks fine'"
    Then the procedure command was refused saying "a third-party picture is always credited"

  Scenario: A third-party picture with its credit closes the step
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    And the Story has a stock cover picked by "Ryan"
    When the checklist is brought up to date after a change
    Then the checklist item "illustration" is "done"
    And the cover keeps its third-party credit line

  Scenario: A missing alt text keeps the step open
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    And the Story has a generated cover with no alt text made from the brief "A locked filing cabinet"
    When the checklist is brought up to date after a change
    Then the checklist item "illustration" is "open"
    When I run "stories step" with "--story story-1 --step illustration --state done --note 'It looks fine'"
    Then the procedure command was refused saying "has no alt text"

  Scenario: A generated cover carries no credit
    Given a Story at the "copywriting" stage
    And the Story's checklist exists
    And the Story has a figure cover approved by "Sierra"
    When the checklist is brought up to date after a change
    Then the checklist item "illustration" is "done"
    And the cover shows no credit line and no approval text
