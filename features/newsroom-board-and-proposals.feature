@brand-agnostic @newsroom-ux-fixtures
Feature: The newsroom board and Proposed Stories read the way an editor expects
  An editor reads the Stories board newest first, opens a story without the page jumping around, and finds the stories that AI
  proposes under one plain name: Proposed Stories. These scenarios use synthetic stories in an isolated browser and never touch
  production.

  Scenario: What AI proposes is called a Proposed Story wherever an editor reads it
    Given an isolated newsroom with synthetic stories
    When the editor looks for the stories AI has proposed
    Then the sidebar, the Needs me filter, the counts and the kind label all say Proposed Stories
    And no editor-facing line calls a proposed story a draft

  Scenario: Every column of the Stories board lists its stories newest first
    Given an isolated newsroom with synthetic stories
    When the editor opens the Stories board at 1440 and 375 pixels
    Then each column lists its stories from the most recently updated to the oldest
    And a story with no date sits at the bottom of its column
    And without that rule a column is ordered by id, which is the order the editor saw before

  Scenario: Opening a story shows a solid detail view that does not jump
    Given an isolated newsroom with synthetic stories
    When the editor opens a story at 1440, 834 and 375 pixels and every animation frame is recorded
    Then the detail view's background is opaque and not fading from its very first frame
    And the detail view stays in one place at one size while the story loads
    And the loading shape is the loaded editor's size, so nothing below it moves when the story arrives
