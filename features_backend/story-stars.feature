Feature: A Story keeps its star rating through every new version, and the rating is never published
  Editors rate a Story one to five stars at any stage, from Idea to after publication. The rating is how the newsroom learns what to publish and how
  to rank and feature it. It sits on the Story's working record beside the stage, and a Story is versioned: every edit, copywriting run or draft
  save creates a new record, so every path that creates a version must carry the rating onto it. A Reference once lost its stars because one
  such path built its row without them. Stars are private: they order things for editors, they never change a Story's stage, status or text,
  and they never reach a published row or any projection. Rating a published Story is a plain update of its working record: it publishes nothing
  again and it creates no version.

  Background:
    Given a Story rated 4 stars

  Scenario: Saving a new version of the Story keeps its rating
    When an editor saves a new version of the Story
    Then the new version has 4 stars from the same editor at the same time
    And the Story has two versions

  Scenario: Saving the draft in place keeps its rating
    When an editor saves the draft in place
    Then the draft still has 4 stars from the same editor at the same time
    And the Story still has one version

  Scenario: A copywriting run that drafts the next version keeps the rating
    When a copywriting run drafts the next version of the Story
    Then the drafted version has 4 stars from the same editor at the same time

  Scenario: Moving the Story to another stage keeps its rating
    When the Story is moved to the "reporting" stage
    Then the Story is at the "reporting" stage with 4 stars

  Scenario: Publishing keeps the rating on the Story and puts none on the published row
    When the Story is published
    Then the Story still has 4 stars
    And the published row has no star field
    And no field of the published row is named like a rating

  Scenario: Unpublishing keeps the rating
    Given the Story is published
    When the Story is unpublished
    Then the Story still has 4 stars

  Scenario: Rating a published Story neither republishes it nor makes a version
    Given the Story is published
    When an editor changes the rating to 2 stars
    Then publishing the Story again changes nothing
    And the Story has one version
    And the published row has no star field

  Scenario: A rating that would reach a published row is refused
    When a published row is built that carries a star rating
    Then it is refused because Story stars are private

  Scenario: A Story nobody rated stays unrated through a new version
    Given a Story nobody rated
    When an editor saves a new version of the Story
    Then the new version has no stars

  Scenario: A site on an older schema is read without the star fields
    Given the Story fields the authoring client asks for
    Then they include the three star fields
    And a site without them is read without those fields
