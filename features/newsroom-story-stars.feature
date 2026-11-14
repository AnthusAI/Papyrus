@brand-agnostic @story-stars
Feature: An editor rates a Story one to five stars in the drawer and the editor, and the board card shows the rating
  Editors decide which Stories to publish and, soon, how the site ranks and features them. The rating is a private signal that must be collected from
  the first Story, at every stage from Idea to after publication. The drawer that opens from a Stories board card and the Story editor each offer the
  same five stars the References page uses. One tap sets the rating, a tap on the same star clears it, and nobody has to give a reason. A filled star
  is a solid shape and an empty one an outline, and the count is written beside them, so a rating reads without colour. Editors do not set a rating on
  the board, so a card only shows it: one solid star and the number in the card's top row, and nothing when the Story is unrated, so the rating takes
  no row of its own. A rating is only a rating: it does not save a draft, move the Story to another stage or publish anything, and a Story that is
  already published stays published. The card, the drawer and the editor show one rating, so a change in one shows in the others at once. A rating
  that cannot be saved says so and shows the rating that was saved. On a phone the five stars are large targets in one row. These scenarios use the
  local preview data in an isolated browser at 375 and 1440 pixels and never touch production.

  Scenario: A Story card shows its rating small, in the card's top row
    Given the Stories board with rated and unrated Stories
    When the editor looks at a rated card and an unrated card
    Then the rated card shows one solid star and the number in its top row, with no row of its own and no controls
    And the unrated card shows no rating
    And tapping the rating on a card opens the Story

  Scenario: One tap in the drawer sets a rating, a second tap clears it, and the card follows
    Given the Stories board with rated and unrated Stories
    When the editor opens an unrated Story and taps the third star, and then taps it again
    Then the drawer shows three solid stars and two outline stars, with the count written beside them, and the card shows the number three
    And the second tap clears the rating and the card shows no rating
    And only ratings were saved, with no draft saved, no stage move and no publication

  Scenario: A published Story can be rated in the editor and stays published
    Given the Story editor open on a published Story
    When the editor rates it one star
    Then the rating is saved by one plain update and the Story is still published with nothing unsaved

  Scenario: A rating that cannot be saved says so and returns to what was saved
    Given the Stories board with rated and unrated Stories
    When the editor taps a star in the drawer while the save fails
    Then the drawer says the rating could not be saved and the drawer and the card show the saved rating

  Scenario: On a phone the stars are large targets in one row
    Given the Stories board with rated and unrated Stories
    When the editor opens the board, a drawer and the editor on a phone
    Then the five stars in the drawer and the editor are at least forty pixels square, in one row, with Lucide icons and nothing scrolling sideways
    And the card's rating stays in its top row
