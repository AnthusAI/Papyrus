@brand-agnostic
Feature: Newsroom Shadcn app chrome
  The ops desk uses an application shell. Reader newspaper chrome stays on
  publication pages, not on /newsroom.

  Scenario: Demo newsroom uses app chrome instead of newsprint
    Given I open the newsroom at 1280 by 900
    Then I should see the newsroom app shell
    And I should not see a newspaper masthead or paper page in the newsroom chrome
    And the newsroom should show the knowledge overview

  Scenario: Deep section pages still omit operational tabs
    Given I open the edition path "/newsroom/sections/news?demo=1" at 1280 by 900
    Then the deep newsroom section page should omit operational tabs
