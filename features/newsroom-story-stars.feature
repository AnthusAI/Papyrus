@brand-agnostic @story-stars
Feature: An editor rates a Story one to five stars, on the board card, in the drawer and in the editor
  Editors decide which Stories to publish and, soon, how the site ranks and features them. The rating is a private signal that must be collected from
  the first Story, at every stage from Idea to after publication. The Stories board card, the drawer that opens from it and the Story editor each
  offer the same five stars the References page uses. One tap sets the rating, a tap on the same star clears it, and nobody has to give a reason. A
  filled star is a solid shape and an empty one an outline, and the count is written beside them, so a rating reads without colour. A rating is only
  a rating: it does not save a draft, move the Story to another stage or publish anything, and a Story that is already published stays published.
  The card, the drawer and the editor show one rating, so a change in one shows in the others at once. A rating that cannot be saved says so and shows
  the rating that was saved. On a phone the five stars are large targets in one row. These scenarios use the local preview data in an isolated browser
  at 375 and 1440 pixels and never touch production.

  Scenario: One tap on a Story card sets a rating and a second tap on the same star clears it
    Given the Stories board with rated and unrated Stories
    When the editor taps the third star on an unrated Story card and then taps it again
    Then the card shows three solid stars and two outline stars, with the count written beside them
    And the second tap clears the rating
    And tapping a star did not open the Story

  Scenario: The drawer and the card are one rating
    Given the Stories board with rated and unrated Stories
    When the editor opens a rated Story and changes its rating in the drawer, and then changes it on the card
    Then the card follows the drawer and the drawer follows the card
    And only ratings were saved, with no draft saved, no stage move and no publication

  Scenario: A published Story can be rated in the editor and stays published
    Given the Story editor open on a published Story
    When the editor rates it one star
    Then the rating is saved by one plain update and the Story is still published with nothing unsaved

  Scenario: A rating that cannot be saved says so and returns to what was saved
    Given the Stories board with rated and unrated Stories
    When the editor taps a star while the save fails
    Then the card says the rating could not be saved and shows the saved rating

  Scenario: On a phone the stars are large targets in one row
    Given the Stories board with rated and unrated Stories
    When the editor opens the board, a drawer and the editor on a phone
    Then the five stars are at least forty pixels square, in one row, with Lucide icons and nothing scrolling sideways
