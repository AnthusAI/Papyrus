Feature: Content actions for the newsroom editor
  The content-actions Lambda exposes derive, save, publish and unpublish so the
  browser never parses Markus itself.

  Scenario: An editor derives, saves, publishes and unpublishes an article through the content actions
    Given a content actions backend
    When the editor derives the article body
    Then the derive response is ok
    When the editor saves the article as a draft
    Then the save response reports a draft item
    When the editor publishes the saved article
    Then the publish response reports version 1
    And a published item exists
    When the editor unpublishes the saved article
    Then no published item exists in the content actions backend

  Scenario: Saving with a stale content hash is rejected
    Given a content actions backend
    And the editor has saved the article as a draft
    When the editor saves again with a stale content hash
    Then the response fails with code "conflict"
