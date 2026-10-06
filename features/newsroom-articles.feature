@brand-agnostic
Feature: Newsroom articles editor
  Staff write, validate, preview, save, publish and unpublish Markus articles
  inside the newsroom app. These scenarios run in demo mode with in-memory data.

  Scenario: The articles list shows draft, published and changed articles with status badges
    Given I open the articles list at 1280 by 900
    Then the articles list should show 3 articles
    And the articles list should show the status badge "Draft"
    And the articles list should show the status badge "Published"
    And the articles list should show the status badge "Published, unpublished changes"

  Scenario: A new article with invalid markup shows a line-numbered error and cannot be published
    Given I open a new article at 1280 by 900
    When I enter the article body:
      """
      A first paragraph.

      :::nope
      """
    Then the article validation errors should include a line-numbered error
    And the article Publish button should be disabled

  Scenario: Saving a valid draft keeps it as a draft
    Given I open a new article at 1280 by 900
    When I enter the article title "Harbor Lights"
    And I enter the article body:
      """
      The lights came on at dusk.
      """
    Then the article should be reported as valid
    And the article preview should show "The lights came on at dusk."
    When I save the article draft
    Then the article status should be "Draft"
    And the article notice should say "Draft saved."

  Scenario: Publishing moves it to Published
    Given I open a new article at 1280 by 900
    When I enter the article title "Night Ferry"
    And I enter the article body:
      """
      The ferry runs until midnight.
      """
    Then the article should be reported as valid
    When I publish the article
    Then the article status should be "Published"
    And the article notice should say "Published as version 1."

  Scenario: Unpublishing returns it to Draft
    Given I open the published demo article at 1280 by 900
    When I unpublish the article and confirm
    Then the article status should be "Draft"

  Scenario: The articles screen fits a 390 px wide viewport
    Given I open the articles list at 390 by 844
    Then the articles screen should not scroll horizontally
    When I open a new article at 390 by 844
    Then the articles screen should not scroll horizontally
    And the article Edit and Preview tabs should be visible

  Scenario: Insert image is disabled until the article is saved
    Given I open a new article at 1280 by 900
    Then the article Insert image button should be disabled
    When I enter the article title "Dockside"
    And I enter the article body:
      """
      Gulls on the pier.
      """
    And I save the article draft
    Then the article notice should say "Draft saved."
    And the article Insert image button should be enabled

  Scenario: Inserting an image adds an image directive at the cursor
    Given I open a new article at 1280 by 900
    When I enter the article title "Harbor Images"
    And I enter the article body:
      """
      The lights came on at dusk.
      """
    And I save the article draft
    Then the article notice should say "Draft saved."
    When I choose the image file "features/fixtures/pixel.png"
    Then the article body should contain "::image{src=\"assets/harbor-images/pixel.png\""
    And the article preview should show the uploaded image

  Scenario: Choosing a file that is not an image leaves the body unchanged
    Given I open a new article at 1280 by 900
    When I enter the article title "Harbor Notes"
    And I enter the article body:
      """
      The lights came on at dusk.
      """
    And I save the article draft
    Then the article notice should say "Draft saved."
    When I choose the image file "package.json"
    Then the article image error should say "Choose a PNG"
    And the article body should not contain "::image"
