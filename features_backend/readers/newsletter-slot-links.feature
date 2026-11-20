Feature: Links in a newsletter slot
  A slot's blurb goes to subscribers under the site's name, so it may carry no address the site did not vouch for. A link must be the slot's own Story page or
  appear in that Story; anything else is refused, naming the link.

  Scenario: The Story's own page and links from the Story are allowed
    Given a Story whose text links to a report
    When a blurb links to the Story's page and to that report
    Then the blurb has no link problems

  Scenario: An invented link is refused
    Given a Story whose text links to a report
    When a blurb links to an address that is neither the Story's page nor in the Story
    Then the blurb is refused naming that link
