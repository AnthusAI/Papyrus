Feature: Revise newsroom story work
  As an editor
  I want to return a story to an earlier editorial stage
  So that revision is represented honestly instead of being performed behind an unchanged status

  Scenario: Return reporting for more research
    Given a story has reached editor selection
    When the editor requests additional research through a supported transition
    Then the story returns to the configured research stage
    And existing assignment, research, and report artifacts remain available

  Scenario: Return reader-facing copy for revision
    Given a story has reached copywriting
    When the editor revises the article artifact while the story remains in copywriting
    Then the story remains in the configured copywriting stage
    And the article artifact reflects the revised copy
