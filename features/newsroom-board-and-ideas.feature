@brand-agnostic @newsroom-ux-fixtures
Feature: The newsroom board and generated ideas read the way an editor expects
  An editor reads the Stories board newest first, opens a story without the page jumping around, and finds the story ideas that AI
  generates in one place under one plain name: ideas, in the Idea column of the Stories board. These scenarios use synthetic stories in an isolated browser and never touch
  production.

  Scenario: What AI generates is an idea, in the Idea column, wherever an editor reads it
    Given an isolated newsroom with synthetic stories
    When the editor looks for the story ideas AI has generated
    Then the Needs me filter, the counts and the card all say ideas, and the sidebar and the Stories board have no Proposed Stories page, link or count
    And no editor-facing line calls an idea a Proposed Story or a draft

  Scenario: Every column of the Stories board lists its stories newest first
    Given an isolated newsroom with synthetic stories
    When the editor opens the Stories board at 1440 and 375 pixels
    Then each column lists its stories from the most recently updated to the oldest
    And a story with no date sits at the bottom of its column
    And without that rule a column is ordered by id, which is the order the editor saw before

  Scenario: The Stories board shows where new stories wait
    Given an isolated newsroom with synthetic stories
    When the editor opens the Stories board
    Then the first column is Idea, ahead of Reporting
    And each Idea card is marked Generated or Started by a person
    And a story at the assignment stage is not on the Stories board

  Scenario: Opening a story shows a solid detail view that does not jump
    Given an isolated newsroom with synthetic stories
    When the editor opens a story at 1440, 834 and 375 pixels and every animation frame is recorded
    Then the detail view's background is opaque and not fading from its very first frame
    And the detail view stays in one place at one size while the story loads
    And the loading shape is the loaded editor's size, so nothing below it moves when the story arrives
