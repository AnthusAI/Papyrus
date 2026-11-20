Feature: Publishing an item to the published projection
  Saving writes a draft Item; publishing projects it to the guest-readable
  PublishedItem; unpublishing removes the projection.

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
