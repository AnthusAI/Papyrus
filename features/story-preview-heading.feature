Feature: The Preview pane of a Story opens with its headline
  A reviewer reads a Story in the console Preview pane the way a reader will meet it: the headline first, in the largest type, then the deck under it,
  then the blurb that describes the Story on the board and in listings. The deck is a line of explanation, so it is never drawn in the headline's place.
  The headline is the front matter title. A Story with no title shows its address instead, so the first line is never a deck or empty.

  Scenario: A title with a dash and a question mark, and a deck with an apostrophe
    Given a Story saved with the title "A Home Surveillance Drone with Cloud AI — What Could Go Wrong?" and a deck that begins "Ring's Drone Cam is sold as security"
    When the Preview pane opens
    Then the headline is the title
    And the deck follows it as the deck, whether the front matter is plain, folded over two lines, or quoted

  Scenario: The headline comes before the deck
    Given a Story with a title and a deck
    When the Preview pane opens
    Then the headline is drawn above the deck and no blurb line appears when the front matter has no blurb

  Scenario: A Story with only a deck still opens with a headline
    Given a Story whose front matter has a deck and no title
    When the Preview pane opens
    Then the headline is the Story's address and the deck is not used as the headline
