Feature: Proposals to change the map
  AI proposes a change to the map: a story draft, a new concept, a rename, a merge, a split, a new column or an element symbol.
  On a site that publishes its proposals (the proposals.publish setting, off by default) the proposal is a public record from the first snapshot after it is filed. It is labelled as a draft and as proposed by AI, readers steer it
  with votes, and an editor decides. A proposal moves through draft, in steering and editor review to approved, declined or
  overridden by editor, and no other road is open. An editor who overrides the community must give a public reason, and readers
  see both results. The public files never name the proposer or the staff member who acted.

  Background:
    Given a publication with proposals
    And an editor and a reader

  Scenario: A filed proposal is a labelled public draft proposed by AI
    When the editor files a "story_draft" proposal titled "Agents are eating the board"
    And the snapshot publishes proposals
    Then the public proposal list holds 1 proposal
    And the first public proposal is in state "draft" labelled "Draft · Proposed by AI"
    And the first public proposal has 0 up, 0 down and 0 net votes
    And no public proposal file names the proposer or a staff member

  Scenario: Every kind of proposal can be filed with the targets it needs
    When the editor files proposals of every kind
    Then 7 proposals are stored as drafts

  Scenario: A merge must name at least two concepts
    When the editor files a "merge" proposal naming 1 concept
    Then the editor is told "invalid_targets"
    And no proposal is stored

  Scenario: A reader cannot file or decide a proposal
    When the reader tries to file a "story_draft" proposal
    Then the reader is told "not_staff"
    And no proposal is stored

  Scenario: A proposal goes to steering, then editor review, then is approved with a decision line
    Given a filed "new_concept" proposal
    When the editor moves it to "in_steering"
    And the editor moves it to "editor_review"
    And the editor decides "approved" saying "Clear evidence."
    And the snapshot publishes proposals
    Then the first public proposal is in state "approved" labelled "Approved · Proposed by AI"
    And the first public proposal shows the editor's decision "approved" saying "Clear evidence."
    And the proposal history reads "draft, in_steering, editor_review, approved"

  Scenario: A transition that is not on the road is refused
    Given a filed "rename" proposal
    When the editor moves it to "approved"
    Then the editor is told "transition_not_allowed"
    And the proposal is still in state "draft"

  Scenario: A decided proposal is final
    Given a filed "split" proposal that was declined
    When the editor moves it to "in_steering"
    Then the editor is told "transition_not_allowed"

  Scenario: An override needs a public reason
    Given a filed "merge" proposal that is in editor review
    When the editor overrides the community declining without a reason
    Then the editor is told "reason_required"
    And the proposal is still in state "editor_review"

  Scenario: An override keeps the community result and the editor's result visible
    Given a filed "merge" proposal that is in editor review
    When the snapshot publishes proposals
    And the editor overrides the community declining saying "Coordinated votes from new accounts."
    And the snapshot publishes proposals again
    Then the first public proposal is in state "overridden_by_editor" labelled "Overridden by editor · Proposed by AI"
    And the first public proposal shows the editor's decision "declined" saying "Coordinated votes from new accounts."
    And the first public proposal still shows the community result from when review began

  Scenario: Two editors cannot both decide from the same view
    Given a filed "story_draft" proposal
    When the editor moves it to "in_steering"
    And a second editor moves it to "declined" from the old view
    Then the second editor is told "target_changed"

  Scenario: Missing vote counts read as zero and published counts come from the subjects snapshot
    Given a filed "story_draft" proposal
    And the subjects snapshot counts 7 up and 2 down on it
    Then the proposal's public votes are 7 up, 2 down and 5 net

  Scenario: The proposal body is Markus kept as written
    When the editor files a "story_draft" proposal with a Markus body
    And the snapshot publishes proposals
    Then the public proposal file holds the Markus body exactly as filed
    And the Markus body renders to the golden fragment

  Scenario: Proposal files are placed under the base path and never reported as orphans
    Given a filed "story_draft" proposal
    When the snapshot publishes proposals under the base path "posts"
    Then the file "posts/_data/proposals/index.json" exists
    And "posts/_data/proposals/index.json" is a plugin runtime file
