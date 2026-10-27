Feature: The router sends feedback for references curated by people, including in the newsroom UI
  The newsroom UI records the editor's sign-in identity, usually an email address, as the curation
  actor. The router treats that as a human curation and tells Cyclotron what the editor decided.
  Cyclotron never receives an email address: the editor is sent as a stable hashed subject.
  Curation by the worker or by AI is not an editor's judgement and is never sent.

  Background:
    Given a router with feedback on and three delivered stories

  Scenario: An accept from the newsroom UI is sent as feedback
    When an editor accepts a reference in the newsroom UI
    And the feedback task runs
    Then one feedback was sent to Cyclotron with the label include
    And the editor subject sent does not contain an email address

  Scenario: A curation by the worker or by AI is not sent
    When the worker accepts a reference and an AI accepts another
    And the feedback task runs
    Then no feedback was sent to Cyclotron
