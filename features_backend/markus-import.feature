Feature: Importing a Markus content directory into the CMS
  Files with front matter and Markus bodies become Items; referenced images
  become MediaAssets. The import is idempotent and never overwrites CMS edits.

  Scenario: Importing a content directory creates items and media
    Given the fixture content directory
    When I import it
    Then 5 items are created and 1 media file is uploaded
    And the article "item-articles-hello" is published with the alias "/blog/hello-old"

  Scenario: Importing twice changes nothing
    Given the fixture content directory
    And I import it
    When I import it again
    Then everything is unchanged
    And no records were written

  Scenario: A CMS edit is not overwritten by a re-import
    Given the fixture content directory
    And I import it
    And the article "item-articles-hello" was edited in the CMS
    When I import it again after changing its source
    Then the article "item-articles-hello" is reported as edited in the CMS
    And its body is still the CMS edit

  Scenario: One bad file aborts the whole import
    Given the fixture content directory
    And a file using the directive "nope"
    When I import it
    Then the import fails naming "bad.md"
    And no records were written
