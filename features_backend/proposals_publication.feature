Feature: Publishing proposals is opt-in
  A proposal is stored as a private record. AI can file story ideas as draft proposals without anything reaching the public
  site. A site publishes its proposals, in every state, only when it opts in with the reader-steering setting
  proposals.publish. The setting is off by default, and the reader snapshot still counts the stored proposals either way.
  Turning the setting off stops further updates; it does not delete files that were already published.

  Background:
    Given a publication with proposals
    And an editor and a reader

  Scenario: A draft proposal is private by default
    When the editor files a "story_draft" proposal titled "Agents are eating the board"
    And the snapshot runs without the publishing setting
    Then no public proposal file is written
    And the snapshot counted 1 stored proposal

  Scenario: A draft proposal stays private when the setting is off
    When the editor files a "story_draft" proposal titled "Agents are eating the board"
    And the snapshot runs with proposal publishing turned off
    Then no public proposal file is written
    And the snapshot counted 1 stored proposal

  Scenario: A site that opts in publishes its proposals
    When the editor files a "story_draft" proposal titled "Agents are eating the board"
    And the snapshot runs with proposal publishing turned on
    Then the public proposal list holds 1 proposal
    And the first public proposal is in state "draft" labelled "Draft · Proposed by AI"
