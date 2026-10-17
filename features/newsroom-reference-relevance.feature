Feature: Editors review the relevance cyclotron's decisions in the References tab
  For each pending candidate reference the relevance cyclotron has decided,
  the References tab shows the decision, how sure it is and why it was sent
  to review. The editor answers with thumbs up or down, one of the existing
  rejection reasons and an optional explanation, through the existing
  curation action.

  @brand-agnostic
  Scenario: An editor sees a decision and why it was sent to review
    Given I open the newsroom path "/newsroom/references/reference-knowledge-corpus-demo-source-history-002?demo=1" at 1280 by 900
    Then the reference detail should show the cyclotron decision "include · 82% sure · version 1"
    And the reference detail should say why the decision was sent to review
    And the reference detail should offer thumbs for "include" and "exclude"
    And no browser console errors should occur

  @brand-agnostic
  Scenario: A thumbs-down review needs one of the existing reasons and rejects the reference
    Given I open the newsroom path "/newsroom/references/reference-knowledge-corpus-demo-source-history-002?demo=1" at 1280 by 900
    When I give the decision a thumbs down
    Then the review cannot be submitted without a reason
    When I choose the reason "Out of scope" and explain "Not our beat."
    And I submit the review
    Then the reference detail should show the status "Rejected"
    And no browser console errors should occur

  @brand-agnostic
  Scenario: The Needs review filter lists the decisions sent to review
    Given I open the references newsroom at 1280 by 900
    When I choose the "Needs review" references filter
    Then the references list should show only "reference-knowledge-corpus-demo-source-history-002"
    And that reference row should be marked "Needs review"

  @brand-agnostic
  Scenario: A reference without a decision keeps the existing curation actions
    Given I open the references newsroom at 1280 by 900
    When I open reference "reference-knowledge-corpus-demo-source-history-001"
    Then the reference detail should render the curation cluster
    And the reference detail should not show a relevance review
