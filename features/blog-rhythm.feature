@blog @rhythm-layout
Feature: Blog vertical rhythm
  A brand that opts into the rhythm blog layout (blogLayout: "rhythm") gets a
  blog presentation whose heights and gaps are whole rhythm rows, with a
  hotkey overlay that shows the grid. Other brands do not render this layout,
  so these scenarios are skipped for them.

  Background:
    Given the active presentation is "blog"
    And I open the "current-edition" layout scenario at 900 by 900

  Scenario: Featured blog items follow the vertical rhythm grid
    Then the blog presentation should follow the vertical rhythm
    And no blog measured line should be cropped
    And featured blog items in obstacle mode should match image height to compressed copy

  Scenario: Blog rhythm overlay toggles with the shared hotkey
    When I toggle the rhythm overlay
    Then the blog rhythm overlay should be visible
