Feature: Every site has the Proposals queue
  The Proposals queue is part of every newsroom backend, not of the reader-steering plugin. AI files its story drafts as
  proposals (monitor stories and Cited Trends), an unattended run lists the existing drafts so it does not file a near-duplicate,
  and editors see each proposal in the newsroom and decide it. A site that has never enabled reader-steering needs no reader
  models, no reader function and no moderation to do any of this: it only upgrades Papyrus and configures its run. A site that does
  have reader-steering, Shipped for one, keeps its Proposal table and its rows exactly as they were; the plugin adds reader votes
  on proposals and public publishing on top of the same table, and it no longer defines the queue itself.

  Background:
    Given a site backend with no plugins
    And the site's automation runs as an operator role
    And an editor and an admin are signed in

  Scenario: A site without reader-steering accepts an AI story draft from an operator
    When the automation files a story draft titled "Agents are eating the board" with a one-line summary
    Then the draft is stored as a core proposal in state "draft" proposed by AI
    And the site has no reader tables

  Scenario: The operator lists the story drafts so it can avoid near-duplicates
    Given the automation filed story drafts titled "First" and "Second"
    When the automation lists the story drafts
    Then the answer holds 2 drafts, newest first
    And each draft shows only its id, title, summary, targets, state and creation time

  Scenario: Editors see a draft and move it to a decision
    Given the automation filed a story draft titled "Agents are eating the board"
    When the editor advances the draft to "in_steering"
    And the editor advances the draft to "editor_review"
    And the admin advances the draft to "approved"
    Then the draft is now in state "approved"
    And its history records 3 moves, none of them naming a person in the public files

  Scenario: An operator may send a draft to steering or decline it and nothing more
    Given the automation filed a story draft titled "Agents are eating the board"
    When the operator advances the draft to "in_steering"
    And the operator advances the draft to "editor_review"
    Then the automation is told "operator_not_allowed"
    And the draft is now in state "in_steering"

  Scenario: Only editors and admins pin, hold or exclude votes
    Given the automation filed a story draft titled "Agents are eating the board"
    When the automation tries to hold the draft
    Then the automation is told "operator_not_allowed"
    When the editor holds the draft
    Then the draft is on hold

  Scenario: Editor steering is complete without readers
    Given the automation filed a story draft titled "Agents are eating the board"
    When the editor pins the draft
    And the editor holds the draft
    Then the draft is pinned and on hold
    When the editor advances the draft to "in_steering"
    Then the editor is refused "proposal_held"
    When the editor releases the draft
    And the editor advances the draft to "in_steering"
    And the editor advances the draft to "editor_review"
    And the editor unpins the draft
    And the admin advances the draft to "declined"
    Then the draft is now in state "declined"
    And the draft is not pinned

  Scenario: Someone who is neither staff nor an operator of this account is refused
    When an identity-pool user tries to file a story draft
    And an operator of another account tries to file a story draft
    Then both callers are told "not_staff"
    And the site stores no proposal

  Scenario: The newsroom shows nothing reader-facing on a site without reader-steering
    Then the Proposals panel is in Administration for every site
    And the panel offers a draft a straight move to editor review, pin, hold and decline
    And the panel says nothing of steering, votes or readers when the site has no reader-steering

  Scenario: Reader-steering builds on the queue instead of defining it
    Then the Proposal model and its operations are defined by the core schema
    And the reader-steering plugin defines none of them
    And the plugin still reads the same table for reader votes and public publishing
