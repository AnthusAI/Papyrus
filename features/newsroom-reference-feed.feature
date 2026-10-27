@brand-agnostic @reference-feed-fixtures
Feature: The References page is a news feed ranked by what the Cyclotron expects the editor to accept
  References open as a feed in a responsive grid, like a news app: a larger lead card, then cards with a picture, a title, a one-line
  dek, the source and its age, the Cyclotron's prediction (Accept or Reject with its confidence and an icon) and the editor's own
  Accept and Reject. The order is the Cyclotron's prediction: the items it expects the editor to Accept most surely come first, the
  items with no prediction sit in the middle, and the strongest predicted Rejects come last. Age fades a prediction toward "not sure"
  and never to the bottom, at a pace learned from how old the editor's accepted References were when accepted; with fewer than ten
  accepted examples nothing is guessed. A card the editor rates stays where it is for the rest of the visit, showing the answer and
  whether the Cyclotron matched it; on the next visit it is under Rated. Unrated items past their freshness move to an Earlier section at
  the bottom and can still be rated. The page shows its shell and card skeletons at once instead of a checking screen, and a return
  visit shows the last saved cards while the live read runs. These scenarios use synthetic References in an isolated browser at 375 and
  1440 pixels and never touch production.

  Scenario: The strongest predictions are first and the strongest Rejects are last
    Given a feed of References with predictions from a strong Accept to a strong Reject and one with no prediction
    When the editor opens the feed at 375 and 1440 pixels
    Then the order runs from the strongest Accept, through the item with no prediction, to the strongest Reject
    And the first card is the large lead card, and the grid has one column on a phone and three or more on a desktop
    And every card shows its title, dek, source, age, the Cyclotron's Accept or Reject with its confidence and icon, and large Accept and Reject buttons
    And nothing scrolls sideways and there are no drop-downs

  Scenario: Age fades a prediction toward not sure, at a pace learned from the editor's own accepts
    Given References whose accepted examples show how quickly the editor acts
    When the feed is ranked
    Then an old prediction keeps only part of its distance from not sure and never falls below a fresh Reject
    And with fewer than ten accepted examples there is no fading and no Earlier section
    And a card rated this visit does not move any other card

  Scenario: A rated card stays in place, shows whether the Cyclotron matched, and is under Rated on the next visit
    Given a feed of References with predictions from a strong Accept to a strong Reject and one with no prediction
    When the editor accepts a card, then rejects it with a reason, and rejects a card the Cyclotron expected to be rejected
    Then each rated card stays in its place and shows Saved
    And the Cyclotron's chip says Match with a check or Miss with a cross, in words and an icon as well as colour
    And Rejecting asks for a reason in words and changes nothing until one is chosen
    And the Rated tab lists the most recent answer first, and the next visit lists the answered cards there

  Scenario: Unrated items past their freshness move to Earlier at the bottom and can still be rated
    Given References older than three times the learned freshness
    When the editor opens the feed at 375 and 1440 pixels
    Then they appear in an Earlier section after everything in the feed, and under the Earlier tab
    And an Earlier card can be rated and stays where it is

  Scenario: A picture that cannot load becomes a tile with the source name
    Given References whose pictures load, fail, or were never found
    When the editor opens the feed at 375 and 1440 pixels
    Then the pictures are lazy, in a fixed frame and requested with no referrer
    And a missing or failing picture shows a tile with the source name and a newspaper icon

  Scenario: The page shows its shell and card skeletons at once, never a checking screen
    Given the References are still loading
    When the editor opens the feed at 375 and 1440 pixels
    Then the page header, the tabs and card skeletons are on screen and no text says it is checking credentials

  Scenario: A return visit shows the last saved cards, read only, until the live read arrives
    Given this browser saved the last feed it showed
    When the editor opens the References page while the session is still being confirmed
    Then the saved cards are shown at once with a note that they are the last view
    And answering is switched off with the reason in words, and a saved copy never answers on its own
    And the saved copy and the session summary expire, survive a blocked or full browser store, and are wiped on sign-out

  Scenario: The ranking is explained in plain words with this site's own numbers
    Given the feed is open
    When the editor opens how this feed is ranked
    Then it explains best bets first, confidence, fading toward not sure, Earlier and why a rated card stays put
    And it says how many accepted examples have been learned from, or how many more are needed
