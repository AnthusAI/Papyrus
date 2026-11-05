Feature: Safe agent Story writes
  An agent must not overwrite a colleague's work or approve its own publication.

  Scenario: Two drafts based on the same Story version compete
    Given a Story has a single current version
    When two drafts are saved against that same expected version
    Then only one becomes the new current version
    And the other is refused without changing the Story

  Scenario: A draft cannot overwrite a previously used version ID
    Given a Story has a single current version
    When another write claims the planned new version ID
    Then the draft is refused without changing the Story

  Scenario: Story writes stay unavailable without an atomic gate-aware operation
    Given the site has no safe agent publishing operation
    When an agent discovers the site's Story tools
    Then the agent cannot call a Story write tool
