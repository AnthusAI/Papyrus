Feature: Operators file AI proposals through IAM
  An unattended automation, such as the idea pipeline or a scheduled run, has no browser sign-in and no editor group. An
  operator's IAM role in the site's own AWS account may file an AI proposal and send a draft either to steering or to declined,
  and nothing more. Every decision after the draft, approving, declining after review and overriding the community, stays with
  editors and admins. An operator never chooses who proposed: the proposal is always proposed by AI, and the history records
  the filing and each move as the operator's principal. A Cognito identity-pool user and a principal of any other AWS account
  are refused, and no public proposal file names the operator.

  Background:
    Given a publication with proposals
    And an operator role in the site's own account

  Scenario: An operator files a draft proposed by AI and the history names the operator
    When the operator files a "story_draft" proposal titled "Filed by automation"
    Then the operator is told "ok"
    And the stored proposal is a draft proposed by "ai"
    And the stored history records the filing by the operator's principal

  Scenario: An operator cannot file a proposal on behalf of a reader
    When the operator files a "story_draft" proposal naming a reader as the proposer
    Then the operator is told "ok"
    And the stored proposal is a draft proposed by "ai"

  Scenario: An operator sends a draft to steering
    Given the operator filed a "new_concept" proposal
    When the operator moves it to "in_steering"
    Then the operator is told "ok"
    And the proposal is still in state "in_steering"
    And the stored history records the move by the operator's principal

  Scenario: An operator declines a draft
    Given the operator filed a "rename" proposal
    When the operator sends it to "declined" because "Duplicate of an earlier proposal."
    Then the operator is told "ok"
    And the proposal is still in state "declined"

  Scenario Outline: An operator cannot approve, review or override
    Given the operator filed a "merge" proposal
    When the operator moves it to "<state>"
    Then the operator is told "operator_not_allowed"
    And the proposal is still in state "draft"

    Examples:
      | state                |
      | approved             |
      | editor_review        |
      | overridden_by_editor |

  Scenario: An operator cannot decide a proposal that is in editor review
    Given a filed "merge" proposal that is in editor review
    When the operator moves it to "approved"
    Then the operator is told "operator_not_allowed"
    When the operator moves it to "declined"
    Then the operator is told "operator_not_allowed"
    And the proposal is still in state "editor_review"

  Scenario: An editor still decides after the operator filed and steered
    Given the operator filed a "story_draft" proposal
    When the operator moves it to "in_steering"
    And the editor moves it to "editor_review"
    And the editor decides "approved" saying "Clear evidence."
    Then the proposal is still in state "approved"

  Scenario: A Cognito identity-pool user is not an operator
    When an identity-pool user tries to file a "story_draft" proposal
    Then the operator is told "not_staff"
    And no proposal is stored

  Scenario: A principal of another AWS account is not an operator
    When a principal of another account tries to file a "story_draft" proposal
    Then the operator is told "not_staff"
    And no proposal is stored

  Scenario: The operator is not named in any public file
    Given the operator filed a "story_draft" proposal
    And the operator moves it to "in_steering"
    When the snapshot publishes proposals
    Then no public proposal file names the operator

  Scenario: An operator lists story drafts with six fields and nothing else
    Given the operator filed a "story_draft" proposal titled "First trend draft" with a one-line summary
    And the operator filed a "new_concept" proposal
    When the operator lists the story drafts
    Then the operator is told "ok"
    And the list holds only the story draft "First trend draft"
    And each listed draft has exactly its id, title, summary, targets, state and createdAt
    And the list holds no body, evidence, history, proposer or vote

  Scenario: A listed draft shows its state after the operator steers or declines it
    Given the operator filed a "story_draft" proposal
    And the operator moves it to "declined"
    When the operator lists the story drafts
    Then the listed draft is in state "declined"

  Scenario: A Cognito identity-pool user cannot list story drafts
    Given the operator filed a "story_draft" proposal
    When an identity-pool user tries to list the story drafts
    Then the operator is told "not_staff"
    And the list is empty

  Scenario: A principal of another AWS account cannot list story drafts
    Given the operator filed a "story_draft" proposal
    When a principal of another account tries to list the story drafts
    Then the operator is told "not_staff"
    And the list is empty
