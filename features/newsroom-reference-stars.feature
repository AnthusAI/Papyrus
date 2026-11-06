@reference-stars
Feature: An editor rates a Reference one to five stars while accepting or rejecting it
  Beside Accept and Reject, every place an editor decides on a Reference offers five stars: the feed card, the detail pane, the Needs me list and the
  Accepted automatically list. One tap sets the rating, a tap on the same star clears it. The rating is optional, needs no reason, works before or after
  a vote, and never changes the vote: stars are the editor's interest, and the idea pipeline reads them. A filled star is a solid shape and an empty
  one an outline, so they read without colour, and the count is written beside them. On a phone the five stars are large targets in one row. The list
  shows each rated Reference's stars as a small solid star and the number.

  Scenario: One tap sets a rating and a second tap on the same star clears it
    Given a References page with unrated, rated and automatically accepted References
    When the editor taps the fourth star on an unrated card and then taps it again
    Then the card shows four solid stars and one outline star, with the count written beside them
    And the second tap clears the rating

  Scenario: Pressing a star lights it and every star to its left
    Given a References page with unrated, rated and automatically accepted References
    When the editor presses the second, then the fifth, then the third star on an unrated card
    Then each press fills that star and every star to its left as solid shapes, leaves the rest as outlines, and writes the count beside them

  Scenario: Rating a pending Reference also accepts it, and stars never overturn a decision
    Given a References page with unrated, rated and automatically accepted References
    When the editor rates a pending card five stars, and accepts another card and then rates it three stars
    Then the rated card is accepted by the same rating with no separate vote, and the accepted card keeps its decision and takes the stars

  Scenario: What is saved is shown, and an automatic acceptance can be rated without being confirmed
    Given a References page with unrated, rated and automatically accepted References
    When the editor includes the rated References
    Then the saved ratings show on their cards and rating an automatic acceptance does not confirm it

  Scenario: The list and the detail pane show and set the rating in step with the card
    Given a References page with unrated, rated and automatically accepted References
    When the editor opens a rated Reference and changes its rating in the detail pane
    Then the card and the list row follow the detail pane

  Scenario: A rating that cannot be saved says so and returns to what was saved
    Given a References page with unrated, rated and automatically accepted References
    When the editor taps a star while the save fails
    Then the card says the rating could not be saved and shows the saved rating

  Scenario: On a phone the stars are large targets in one row
    Given a References page with unrated, rated and automatically accepted References
    When the editor opens the page on a phone
    Then the five stars are at least forty pixels square, in one row, with Lucide icons and nothing scrolling sideways
