@backend @related-links-requests
Feature: Opening a Reference with links, and asking for more suggestions, does not read the site's whole graph
  The Related section labels the few concepts and References a Reference is linked to. It used to load every concept of the site, page after page in the
  browser, to do it, so on a site with thousands of nodes "Suggest more" kept spinning for a long time after the server had finished in seconds. Now each
  concept and Reference is read by its own id, all at once, so the number of requests is the number of things shown and does not depend on how many nodes the
  site has. The suggestions appear as soon as the server has made them; the list is read again behind them. The add box still reads the concepts or the
  References once, when someone first types in it.

  Scenario: A Reference with 2 concept links and 3 related References makes one request for each, however many nodes the site has
    Given a site with 5000 concepts
    When the labels of 2 concept links and 3 related References are resolved
    Then 2 concepts and 3 References were each read once by id
    And no request listed all the concepts or all the References
