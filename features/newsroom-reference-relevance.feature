Feature: Editors review the relevance cyclotron's decisions in the References tab
  For each pending candidate reference the relevance cyclotron has decided,
  the References tab shows the decision, how sure it is and why it was sent
  to review. The editor answers with thumbs up or down, one of the existing
  rejection reasons and an optional explanation, through the existing
  curation action.

  @brand-agnostic
  Scenario: An editor sees the Cyclotron's answer next to their own
    Given I open the newsroom path "/newsroom/references/reference-knowledge-corpus-demo-source-history-002?demo=1" at 1280 by 900
    Then the prediction marks "Accept" and the bar says "82%"
    And the control offers Accept and Reject
    And no browser console errors should occur

  @brand-agnostic
  Scenario: Rejecting needs one of the existing reasons and rejects the reference
    Given I open the newsroom path "/newsroom/references/reference-knowledge-corpus-demo-source-history-002?demo=1" at 1280 by 900
    When I tap Reject
    Then the card asks for a reason in words
    When I explain "Not our beat." and record it
    Then the reference detail should show the status "Rejected"
    And the prediction's marker shows the answer differs from it
    And no browser console errors should occur

  @brand-agnostic
  Scenario: The Needs review filter lists the decisions sent to review
    Given I open the references newsroom at 1280 by 900
    When I choose the "Needs review" references filter
    Then the references list should show only "reference-knowledge-corpus-demo-source-history-002"
    And that reference row should be marked "Needs review"

  @brand-agnostic
  Scenario: Every pending reference with a cyclotron suggestion is counted and listed under Needs review
    Given I open the references newsroom at 1280 by 900
    When I choose the "Needs review" references filter
    Then the "Needs review" tab count should equal the references listed
    And every listed reference should show a cyclotron suggestion

  @brand-agnostic
  Scenario: A reference without a decision keeps the existing curation actions
    Given I open the references newsroom at 1280 by 900
    When I open reference "reference-knowledge-corpus-demo-source-history-001"
    Then the reference detail should render the curation cluster
    And the control should say there is no prediction
