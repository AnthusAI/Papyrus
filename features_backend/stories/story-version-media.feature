Feature: Saving a new version of a story keeps its images
  A story's images are stored as media rows that belong to one saved version of the story. Saving a new version creates a
  new version record, so without care the new version would have no images and could not be published: publishing refuses
  an article whose text points at a local image that has no media row on that version. When a new version is saved, every
  local image its text uses is attached to it again, copied from the most recent earlier version that has it, searching all
  earlier versions so that a version saved before this rule existed does not hide the images of older ones. An image that
  no earlier version has is left alone, and publishing still reports it as missing, which is correct.

  Scenario: A new version of an article with an image can still be published
    Given a story whose first version uses the image "images/chart.png" with a media row
    When the editor saves a second version that still uses the image
    Then the second version has a media row for "images/chart.png"
    And the second version can be published

  Scenario: A version saved without images is repaired by the next save
    Given a story whose first version uses the image "images/chart.png" with a media row
    And the editor saves a second version that drops the image
    When the editor saves a third version that uses the image again
    Then the third version has a media row for "images/chart.png"
    And the third version can be published

  Scenario: An image that no earlier version has still blocks publishing
    Given a story whose first version uses the image "images/chart.png" without a media row
    When the editor saves a second version that still uses the image
    Then the second version has no media rows
    And publishing the second version reports the image as missing
