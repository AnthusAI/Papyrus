@requires-cyclotron
Feature: Relevance decisions and reviews live in the newsroom's own records
  A decision is a relation from the candidate reference to a decision node,
  a newer decision supersedes the older one, the status snapshot is a raw
  payload, and an editor's curation becomes a cyclotron label by the
  existing scope-training rule.

  Scenario: A decision becomes the reference's current relevance decision
    Given a pending reference
    And a relevance decision of "include" at 82% sent to review as a random audit
    When the decision is recorded
    Then the reference has one current relevance decision of "include"
    And the decision records its confidence, cyclotron classifier, version and that review is recommended
    And the decision node "relevance.include" is recorded

  Scenario: A newer decision supersedes the older one
    Given a pending reference with a current relevance decision
    And a relevance decision of "exclude" at 75% not sent to review
    When the decision is recorded
    Then the older decision is superseded
    And the reference has one current relevance decision of "exclude"

  Scenario: Relevance decisions stay out of knowledge queries
    When the relation type "relevance_decision_is" is looked up
    Then it is an operational workflow relation that knowledge queries exclude

  Scenario: The status snapshot is a raw payload the newsroom can read
    Given a cyclotron status snapshot
    When the snapshot is recorded
    Then it is a raw payload for the cyclotron with the snapshot as its private attachment

  Scenario Outline: An editor's curation becomes a cyclotron label by the scope-training rule
    Given a reference curated as "<status>" with reason "<reason>"
    When its cyclotron label is read
    Then the label is "<label>"

    Examples:
      | status   | reason           | label   |
      | accepted |                  | include |
      | rejected | out_of_scope     | exclude |
      | rejected | policy_exclusion | exclude |
      | rejected | duplicate        | none    |
      | archived |                  | none    |
