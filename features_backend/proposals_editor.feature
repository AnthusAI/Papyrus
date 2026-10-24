Feature: Editors steer proposals beyond approving and declining
  Readers vote on a proposal and an editor decides. The editor tier gives editors and admins the rest of the tools: pin a
  proposal so a site can float it, put it on hold so nobody moves it by accident, override the community with a public reason
  while the community's own result stays visible beside it, exclude a batch of votes (for example from accounts under 24 hours
  old when they voted) and undo that, and see which proposals need a look. Excluded votes no longer count, and the public files
  say how many were left out and why. The votes of limited or banned (spam) accounts never count on a proposal. Only editors and
  admins can do any of this: readers, anonymous callers and an IAM operator are refused, and nothing the editors use to decide,
  such as the needs-a-look reasons or who acted, reaches a public file.

  Background:
    Given a publication with proposals that take votes
    And a proposal in steering

  Scenario: Pinning a proposal shows in the public entry and can be undone
    When the editor pins it
    And the snapshot publishes proposals with votes
    Then the first public proposal is pinned
    When the editor unpins it
    And the snapshot publishes proposals with votes
    Then the first public proposal is not pinned

  Scenario: A proposal on hold cannot move until it is released
    When the editor puts it on hold
    And the editor moves it to "editor_review"
    Then the editor is told "proposal_held"
    And the proposal is still in state "in_steering"
    When the editor releases it
    And the editor moves it to "editor_review"
    Then the editor's request is accepted

  Scenario: An override keeps the community result and shows the editor's result with the public reason
    Given 3 seasoned readers vote up
    And the proposal is in editor review
    When the snapshot publishes proposals with votes
    And the editor overrides the community declining saying "Sources are weak."
    And the snapshot publishes proposals with votes
    Then the first public proposal shows the override "declined" saying "Sources are weak."
    And the first public proposal still shows 3 up votes in its community result

  Scenario: An override without a public reason is refused
    Given the proposal is in editor review
    When the editor overrides the community declining without a reason
    Then the editor is told "reason_required"

  Scenario: Excluding votes from new accounts takes them out of the tally and says so publicly
    Given 3 seasoned readers vote up
    And 4 brand-new accounts vote down
    When the snapshot publishes proposals with votes
    Then the first public proposal has 3 up and 4 down votes
    When the editor excludes votes from accounts under 24 hours old
    And the snapshot publishes proposals with votes
    Then the first public proposal has 3 up and 0 down votes
    And the first public proposal says "Excluded 4 votes from accounts under 24 h"

  Scenario: Undoing an exclusion counts the votes again and the note goes
    Given 3 seasoned readers vote up
    And 4 brand-new accounts vote down
    And the editor excluded votes from accounts under 24 hours old
    When the editor undoes that exclusion
    And the snapshot publishes proposals with votes
    Then the first public proposal has 3 up and 4 down votes
    And the first public proposal has no exclusion note

  Scenario: The community result is fixed again without the excluded votes
    Given 3 seasoned readers vote up
    And 4 brand-new accounts vote down
    And the proposal is in editor review
    When the snapshot publishes proposals with votes
    Then the first public proposal still shows 4 down votes in its community result
    When the editor excludes votes from accounts under 24 hours old
    And the snapshot publishes proposals with votes
    Then the first public proposal still shows 0 down votes in its community result

  Scenario: The votes of limited and banned accounts do not count
    Given 4 seasoned readers vote up
    When the editor limits seasoned reader 0
    And the editor bans seasoned reader 1 as spam
    And the snapshot publishes proposals with votes
    Then the first public proposal has 2 up and 0 down votes
    And the first public proposal says "Excluded 2 votes from limited or spam accounts"

  Scenario: A surge of votes from new accounts needs a look, with the reason, until the votes are excluded
    Given 3 seasoned readers vote up
    And 6 brand-new accounts vote up
    When the snapshot publishes proposals with votes
    Then the proposal needs a look because of "new_account_surge"
    When the editor excludes votes from accounts under 24 hours old
    And the snapshot publishes proposals with votes
    Then the proposal does not need a look

  Scenario: A spike of votes needs a look
    Given 12 seasoned readers vote up
    When the snapshot publishes proposals with votes
    Then the proposal needs a look because of "vote_spike"

  Scenario: A community against the AI that proposed it needs a look
    Given 1 seasoned reader votes up and 5 vote down
    When the snapshot publishes proposals with votes
    Then the proposal needs a look because of "community_ai_disagreement"

  Scenario: What editors use to decide never reaches a public file
    Given 12 seasoned readers vote up
    And the editor pins it
    And the editor excluded votes from accounts under 24 hours old
    When the snapshot publishes proposals with votes
    Then no public proposal file holds needs-a-look reasons, the editor log or an editor's id

  Scenario Outline: A reader cannot use the editor tools
    When a reader tries to <action>
    Then the caller is told "not_staff"
    And the proposal is not pinned or on hold

    Examples:
      | action                          |
      | pin the proposal                |
      | hold the proposal               |
      | exclude votes from new accounts |

  Scenario: An anonymous caller cannot use the editor tools
    When an anonymous caller tries to pin the proposal
    Then the caller is told "not_staff"
    And the proposal is not pinned or on hold

  Scenario Outline: An operator cannot use the editor tools
    Given an operator role in the site's own account
    When the operator tries to <action>
    Then the caller is told "operator_not_allowed"
    And the proposal is not pinned or on hold

    Examples:
      | action                             |
      | pin the proposal                   |
      | hold the proposal                  |
      | exclude votes from new accounts    |

  Scenario: An invalid exclusion rule is refused
    When the editor asks to exclude votes by the rule "everyone"
    Then the editor is told "invalid_rule"
