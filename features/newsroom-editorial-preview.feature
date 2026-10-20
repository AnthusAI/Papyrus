@brand-agnostic
Feature: Editorial findings on the article preview
  Editors see editorial findings where readers would see the words: on the
  rendered preview as well as in the markup. They can open a finding where it is
  marked, ask for rewrite options, pick one, or dismiss the finding, and they can
  select any passage of the preview and ask for rewrites of it. These scenarios
  run in demo mode, whose editorial checks flag a few stock phrases.

  Background:
    Given I open a new article at 1400 by 1000
    When I enter the article body:
      """
      # Launch notes

      Our caching layer is **game-changing** for teams. Builds finish in 4 minutes instead of 9.

      We utilize a shared volume.
      """
    And I check the article's editorial policies

  Scenario: Findings are marked in the markup and on the preview
    Then the body editor marks "game-changing" and "utilize"
    And the preview marks "game-changing" and "utilize"

  Scenario: Pick a rewrite for a finding from the preview
    When I open the preview finding on "game-changing"
    And I ask for rewrite options in the preview
    Then the preview shows rewrite options
    When I use the first rewrite option
    Then the article body should contain "Our caching layer cuts build times for teams."
    And the preview no longer marks "game-changing"

  Scenario: Use a deterministic fix from the preview
    When I open the preview finding on "utilize"
    And I use the suggested replacement "use"
    Then the article body should contain "We use a shared volume."

  Scenario: Dismiss a finding from the preview
    When I open the preview finding on "utilize"
    And I dismiss the finding
    Then the preview no longer marks "utilize"
    And the body editor no longer marks "utilize"

  Scenario: Rewrite a passage selected on the preview
    When I select "Builds finish in 4 minutes" on the preview
    And I ask for rewrites of the preview selection
    Then the preview shows rewrite options for "Builds finish in 4 minutes instead of 9."
