Feature: The router sends feedback for references curated by people, including in the newsroom UI
  The newsroom UI records the editor's sign-in identity, usually an email address, as the curation
  actor. The router treats that as a human curation and tells Cyclotron what the editor decided.
  Cyclotron never receives an email address: the editor is sent as a stable hashed subject.
  Curation by the worker or by AI is not an editor's judgement and is never sent.

  Background:
    Given a router and three delivered stories

  Scenario: An accept from the newsroom UI is sent as feedback
    When an editor accepts a reference in the newsroom UI
    And the feedback task runs
    Then one feedback was sent to Cyclotron with the label include
    And the editor subject sent does not contain an email address

  Scenario: A curation by the worker or by AI is not sent
    When the worker accepts a reference and an AI accepts another
    And the feedback task runs
    Then no feedback was sent to Cyclotron

  Scenario: Feedback for an item decided under an older binding is sent under the current binding
    Given the publication binding has since moved to revision 4 with unchanged criteria
    When an editor accepts a reference in the newsroom UI
    And the feedback task runs
    Then one feedback was sent to Cyclotron with the label include
    And the feedback was sent under binding revision 4

  Scenario: A vote made under criteria that have since changed is dropped, not relabelled
    Given the publication binding has since moved to revision 4 with changed criteria
    When an editor accepts a reference in the newsroom UI
    And the feedback task runs
    Then no feedback was sent to Cyclotron that was accepted
    And the vote was recorded as stale

  Scenario: A binding-changed refusal is retried on the next run
    Given Cyclotron answers feedback with publication binding changed
    When an editor accepts a reference in the newsroom UI
    And the feedback task runs
    Then the feedback stays queued for the next run
    When Cyclotron accepts feedback again
    And the feedback task runs
    Then the feedback was delivered on the second attempt with the same request id

  Scenario: A vote is sent when the criteria fingerprint still matches, whatever the binding revision
    Given the publication binding has since moved to revision 4 with changed criteria
    And the vote was stored under criteria fingerprint "c-1" and the publication's criteria are still "c-1"
    When an editor accepts a reference in the newsroom UI
    And the feedback task runs
    Then one feedback was sent to Cyclotron with the label include
    And the feedback was sent under binding revision 4

  Scenario: A vote is dropped when the criteria fingerprint has changed since the vote
    Given the publication binding has since moved to revision 4 with unchanged criteria
    And the vote was stored under criteria fingerprint "c-1" and the publication's criteria are now "c-2"
    When an editor accepts a reference in the newsroom UI
    And the feedback task runs
    Then no feedback was sent to Cyclotron that was accepted
    And the vote was recorded as stale

  Scenario: A Cyclotron-decided live monitor always sends editors' feedback; there is no switch
    Given the stored router config has no feedback setting
    When an editor accepts a reference in the newsroom UI
    And the feedback task runs
    Then one feedback was sent to Cyclotron with the label include

  Scenario: A feedback setting left over in an old stored config is ignored
    Given the stored router config still says feedback is false
    When an editor accepts a reference in the newsroom UI
    And the feedback task runs
    Then one feedback was sent to Cyclotron with the label include

  Scenario: An automatic acceptance is not sent to Cyclotron as an editor's label
    When the Cyclotron accepts a reference automatically
    And the feedback task runs
    Then no feedback was sent to Cyclotron that was accepted
    And the automatic acceptance stays queued as not a human curation

  Scenario: A later editor Reject of an automatically accepted reference is sent as feedback
    Given the Cyclotron accepted a reference automatically and the feedback task ran
    When an editor rejects that reference in the newsroom UI
    And the feedback task runs
    Then one feedback was sent to Cyclotron with the label exclude
    And the editor subject sent does not contain an email address

  Scenario: A later editor Accept of an automatically accepted reference is sent as feedback
    Given the Cyclotron accepted a reference automatically and the feedback task ran
    When an editor accepts that reference in the newsroom UI
    And the feedback task runs
    Then one feedback was sent to Cyclotron with the label include

  Scenario: An acceptance by a monitor's rule is not sent to Cyclotron either
    When a monitor's rule accepts a reference automatically
    And the feedback task runs
    Then no feedback was sent to Cyclotron that was accepted
    And the automatic acceptance stays queued as not a human curation
