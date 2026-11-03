@brand-agnostic @reference-feed-fixtures
Feature: One search box on the References page finds a Reference again, whatever its state
  The newsroom References page has one search box above Sort and Show. Pressing Enter searches the words of every Reference's title, authors,
  link and id, and the meaning of its summary, together, over Unrated, Accepted and Rejected References alike, and answers with the ordinary cards
  the feed shows, each saying in words how it matched: "Matched: title, author", "Matched: meaning" or "Matched: title and meaning". The query
  is in the address as ?q=. While a search is open, Sort reads Relevance, Show opens on All without changing the choice saved in this browser, and
  clearing the search brings the saved choices back. A search has no lead card and no new-items pill, pages with the feed's own infinite scroll,
  and never shows a card twice. These scenarios use synthetic References in an isolated browser at 375 and 1440 pixels and never touch production.

  Scenario: An exact author name finds a rejected Reference
    Given a synthetic site with unrated, accepted and rejected References
    When the editor types an author's full name in the search box and presses Enter
    Then the rejected Reference by that author is the one card, showing its Reject, with "Matched: author"
    And the search box is above Sort and Show, the address carries ?q=, and nothing scrolls sideways at 375 pixels

  Scenario: A word from a title finds an unrated Reference
    Given a synthetic site with unrated, accepted and rejected References
    When the editor searches for a word that is in one unrated Reference's title
    Then that Reference is listed with "Matched: title", with the same Accept and Reject controls as in the feed
    And there is no large lead card and no new-items pill

  Scenario: A conceptual phrase finds a Reference by meaning and says so
    Given a synthetic site with unrated, accepted and rejected References
    When the editor searches for a concept that a Reference's summary is about but its words do not contain
    Then that Reference is listed with "Matched: meaning"

  Scenario: A match on both words and meaning ranks first and says so
    Given a synthetic site with unrated, accepted and rejected References
    When the editor searches for a phrase that one Reference matches by its title and by meaning
    Then that Reference is the first card and says "Matched: title and meaning"
    And the cards that match only by words or only by meaning follow it, each saying how

  Scenario: Sort reads Relevance and Show opens on All without changing what the editor saved
    Given a browser that saved Rated as its Show choice
    When the editor searches, narrows Show to Unrated, and then clears the search
    Then Sort reads Relevance in place of Predictions and Newest, and Show opened on All
    And choosing Unrated during the search did not change the saved choice
    And clearing the search brings back Sort, the saved Show of Rated, and a plain address

  Scenario: The address opens the page already searching
    Given a synthetic site with unrated, accepted and rejected References
    When the editor opens the References page with ?q= and a name
    Then the search box holds that name and its results are listed

  Scenario: Nothing matches, and nothing matches within the chosen Show
    Given a synthetic site with unrated, accepted and rejected References
    When the editor searches for words nothing contains, and then for a name that only a rated Reference has while Show is Unrated
    Then the first says no References match what was typed, in words
    And the second says "No unrated matches" and offers a Show all button that lists the match

  Scenario: Meaning search failing still shows the word results
    Given a synthetic site where meaning search is unavailable
    When the editor searches for a word in one title
    Then the word results stay, with a line saying the search used words only because meaning search is unavailable
    And a Retry button searches again, and when both parts then work the line goes
    And when both word search and meaning search are unavailable the feed's own error appears with its Retry

  Scenario: Paging never repeats a card
    Given a synthetic site with unrated, accepted and rejected References
    When the editor searches for a phrase that more than one page of References match and scrolls to the end
    Then the next page is asked for with the site's cursor, 24 at a time, and no card appears twice

  Scenario: A card voted on during a search stays where it is
    Given a synthetic site with unrated, accepted and rejected References
    When the editor accepts the third card of a search
    Then it shows the answer and no card moves
