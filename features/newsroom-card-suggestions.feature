@card-suggestions
Feature: An editor decides the suggested links on the card they are curating
  Under the stars and Accept and Reject, the Reference feed card and the Needs me Reference card show the few most likely suggested concepts and related
  References for that Reference: at most two of each kind, most likely first, each with Accept and Reject. One tap records the decision with the same call the
  Related section uses, and the suggestion leaves the card; deciding a suggestion is not a vote on the Reference. A card with no suggestions shows nothing and
  keeps its height. Suggestions are read only for the cards on screen, a few at a time and never twice, so a long feed does not read every Reference at once. On
  a phone the buttons are large targets, nothing scrolls sideways and every icon is Lucide. Beside the suggestions a small box adds a
  concept by typing its hashtag, with one button and no dialog, through the same action as the Related section.

  Scenario: The card shows the two most likely suggestions of each kind
    Given a feed whose first Reference has three suggested concepts and three suggested References
    When the first card is on screen
    Then it shows two concepts and two References, most likely first, and a card with none shows nothing

  Scenario: One tap accepts or rejects a suggestion
    Given a feed whose first Reference has three suggested concepts and three suggested References
    When the editor accepts a suggested concept and rejects a suggested Reference on the card
    Then each decision is recorded with the Related section's call and the Reference itself is not voted on

  Scenario: A small box tags the Reference with a hashtag in one tap
    Given a feed whose first Reference has three suggested concepts and three suggested References
    When the editor types a hashtag in the box on a card and taps Create and tag
    Then the Reference is tagged through the Related section's own action

  Scenario: Only the cards on screen are read
    Given a feed of forty References
    When the feed has loaded
    Then only the visible cards read their suggestions and none is read twice

  Scenario: On a phone the buttons are large
    Given a feed whose first Reference has three suggested concepts and three suggested References
    When the editor opens the page on a phone
    Then Accept and Reject are at least forty pixels tall, nothing scrolls sideways and the icons are Lucide
