Feature: Publishing makes a draft readable to guests and unpublishing takes it back
  Saving writes a draft that only the newsroom can read. Publishing copies it to the published record that guests read, and
  unpublishing removes that copy again. Publishing a second time with nothing changed does nothing, and a body that uses a
  directive Papyrus does not know cannot be published at all.

  Scenario: Publishing a draft makes it readable
    Given a saved draft article
    When I publish the item
    Then the published item exists with version 1
    And the item status is "published"

  Scenario: Unpublishing removes it from the published projection
    Given a saved draft article
    And I publish the item
    When I unpublish the item
    Then no published item exists
    And the item status is "draft"

  Scenario: Republishing unchanged content does nothing
    Given a saved draft article
    And I publish the item
    When I publish the item again
    Then the publish reports no change
    And no records were written

  Scenario: A body with an unknown directive cannot be published
    When I try to save an article using the directive "nope"
    Then saving fails with code "markus-validation"
    And no records were written
