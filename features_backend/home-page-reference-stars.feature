Feature: A list of accepted References shows the stars an editor gave each one
  Ryan, 2026-11-04: lists of accepted References on public pages show the star rating. This reverses the earlier rule that stars changed the order of the
  page but were never printed. The count (1 to 5) is on the Reference's record in the snapshot as "stars", and the tile and the row show it. Who rated a
  Reference and when are still private and appear in no file.

  What a card shows:
  - an accepted Reference with a rating shows five Lucide star icons, one filled for each star given and the rest outlined, so the shape carries the value
    and colour never does. The words "4 of 5 stars" are there for a screen reader. The tile carries data-stars="4" on its article, and the stars mark carries
    data-stars="4" too, for sites that style or read it.
  - an accepted Reference nobody rated shows no stars. It shows the Cyclotron's confidence if it has one, by the rules it always had: not on a Reference an
    editor accepted, because once a person has accepted it the prediction no longer matters.
  - a pending (recommended) Reference keeps showing the Cyclotron's confidence. It may be rated, and the rating still ranks it, but its stars are not shown
    until an editor accepts it.
  The order of the cards is unchanged by this: it is the shared order of ratings and then confidence.

  Background:
    Given a home-page site whose pages place confident, recommended, recent, weekly, daily and weekly confident grids

  Scenario: A rated accepted tile shows its stars as filled and outlined shapes with the words for a screen reader
    Given editors rated these References: "Accepted one" 4, "Accepted eight" 2
    When the home-page-snapshot task runs
    Then the "confident" grid on "by-confidence/index.html" shows "Accepted one" with 4 stars
    And the "confident" grid on "by-confidence/index.html" shows "Accepted eight" with 2 stars

  Scenario: An accepted Reference nobody rated shows no stars
    Given editors rated these References: "Accepted one" 4
    When the home-page-snapshot task runs
    Then the "confident" grid on "by-confidence/index.html" shows "Accepted two" with no stars

  Scenario: A pending Reference keeps showing the Cyclotron's confidence even when it is rated
    Given editors rated these References: "Pending mid" 5
    When the home-page-snapshot task runs
    Then the "recommended" grid on "suggested/index.html" shows "Pending mid" with no stars
    And the "recommended" grid on "suggested/index.html" shows "Pending mid" with its confidence

  Scenario: A rating changed after the page was built reaches the tile, and clearing it takes the stars away
    Given editors rated these References: "Accepted one" 4
    And the home-page-snapshot task has run
    When an editor rates "Accepted one" 1 stars and the home-page-snapshot task runs again
    Then the "confident" grid on "by-confidence/index.html" shows "Accepted one" with 1 stars
    When an editor clears the rating of "Accepted one" and the home-page-snapshot task runs again
    Then the "confident" grid on "by-confidence/index.html" shows "Accepted one" with no stars

  Scenario: The stylesheet draws a star filled or outlined and no border
    Given editors rated these References: "Accepted one" 4
    When the home-page-snapshot task runs
    Then the home-page stylesheet fills a star by shape and draws no border around it
