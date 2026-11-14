@brand-agnostic
Feature: Newsroom Shadcn app chrome
  The newsroom uses one application shell, the organizer. Reader newspaper / Markus chrome
  is a separate renderer axis and is not implied by the ops shell.

  Scenario: Demo newsroom uses app chrome instead of newsprint
    Given I open the newsroom at 1280 by 900
    Then I should see the newsroom app shell
    And I should not see a newspaper masthead or paper page in the newsroom chrome
    And the newsroom should show the knowledge overview

  Scenario: The overview focuses on the Notification Center
    Given I open the newsroom at 1280 by 900
    Then the newsroom overview should focus on the Notification Center
    And the newsroom overview should keep its main navigation available
