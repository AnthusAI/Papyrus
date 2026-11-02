Feature: A story's summary reaches the public site whichever field holds it
  The newsroom shows a story's deck, so an editor who fills in a deck expects
  readers to see it. The projector takes the summary from the first field that
  has text, and a deck is one of those fields, on the page and in the public
  data alike. A story with both a description and a deck keeps its description.

  Background:
    Given a site with public data and a story "only-deck" whose front matter has only a deck "A deck for readers."
    And a story "both" with the description "The description." and the deck "An unused deck."

  Scenario: A deck becomes the summary when nothing else is written
    When the site is projected
    Then the meta description of "only-deck" is "A deck for readers."
    And the latest list gives "only-deck" the summary "A deck for readers."

  Scenario: A description still wins over a deck
    When the site is projected
    Then the meta description of "both" is "The description."
    And the latest list gives "both" the summary "The description."
