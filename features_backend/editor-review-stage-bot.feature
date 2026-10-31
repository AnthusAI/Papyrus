@backend @editor-agents
Feature: The editor reviews a story version before it moves on
  A publication can name an editor-review procedure to run when a story enters the copywriting stage. The editor
  reads the version, its linked References, the brief and the publication's editorial context, runs the editorial
  check, and judges the version against acceptance criteria: every outside claim attributed and linked, every number
  about the publisher's own systems traceable, no present-tense claim about its operations that it cannot show, dates
  sourced, promises kept, tables checked by hand (the editorial check skips them) and the version fitting the
  doctrine. The review is a record on the version (Item.metadata.editorReview). The editor answers the engine with the
  stage-bot contract: an approval lets the engine advance the story to typesetting; a revision or a reframe holds it,
  and the engine raises a flag review request. The editor never edits the version, never moves the stage itself, never
  publishes and never writes a Message. The model calls are faked in these specs.

  Background:
    Given a story in the copywriting stage with a table in its body and an editor-review bot that moves stories to typesetting

  Scenario: An approving review advances the story to typesetting
    When the editor approves the version
    Then the story is in the typesetting stage
    And the version records an editor review with verdict "approve", the model, the context hash and the time
    And no review request is raised

  Scenario: A review that asks for a revision holds the story and records the notes
    When the editor asks for a revision because the promised links are missing, with the note "Link every row to its file."
    Then the story is still in the copywriting stage
    And a flag review request raised by the bot mentions "Link every row to its file."
    And the version records the revision notes "Link every row to its file."
    And the version records the failed criterion "promises-kept"

  Scenario: A reframe holds the story
    When the editor asks for a reframe with the note "The evidence supports a smaller story."
    Then the story is still in the copywriting stage
    And a flag review request raised by the bot mentions "reframe"

  Scenario: The review records an illustration plan and a typesetting plan for the later stages
    When the editor approves the version
    Then the version records an illustration plan and a typesetting plan

  Scenario: Without a brief, the doctrine and policies are the brief
    When the editor reads the inputs for the version
    Then the brief source is "none" and the inputs say the editorial context is the brief
    And the inputs carry the editorial context text and its hash

  Scenario: A brief on the version or on the copywriting Assignment is read when there is one
    Given the copywriting Assignment has a brief attachment reading "Angle: show the audit trail."
    When the editor reads the inputs for the version
    Then the brief source is "assignment-attachment" and its text is "Angle: show the audit trail."

  Scenario: The inputs hand the reviewer the tables the editorial check skips
    When the editor reads the inputs for the version
    Then the inputs list one table and the editorial check result

  Scenario: An approval cannot stand over an error-level failure
    When the editor approves although "claims-attributed-and-linked" failed at error severity
    Then the story is still in the copywriting stage
    And the version records the verdict "revise", downgraded from "approve"

  Scenario: An approval cannot stand when a criterion was never assessed
    When the editor approves but never assessed "dates-sourced"
    Then the story is still in the copywriting stage
    And the version records the failed criterion "dates-sourced"

  Scenario: A table that was not checked blocks an approval
    When the editor approves and marks the tables criterion not applicable
    Then the story is still in the copywriting stage

  Scenario: An error-level violation in the editorial check blocks an approval
    Given the editorial check found an error-level violation of "no-hype"
    When the editor approves the version
    Then the story is still in the copywriting stage
    And the version records the verdict "revise", downgraded from "approve"

  Scenario: An answer that is not a review fails the run and stores nothing
    When the editor answers with the verdict "publish"
    Then the review is refused and the version has no editor review

  Scenario: The editor never publishes, never edits and never writes a Message
    When the editor asks for a revision because the promised links are missing, with the note "Link every row to its file."
    Then the version's body, state and status are unchanged
    And no Message and no published item exists
