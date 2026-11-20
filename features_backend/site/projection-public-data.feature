Feature: Public JSON files for static sites
  A site that opts in gets a search index and a latest-items list next to its
  pages. They are rewritten exactly when their content moves, never for an edit
  they do not show, and they carry only what the page HTML already shows.

  Background:
    Given a site with public JSON of six published articles that has been projected

  Scenario: The files exist and list every article
    Then the page "_data/search-index.json" mentions "/articles/bravo.html"
    And the page "_data/latest.json" mentions "/articles/foxtrot.html"
    And the page "_data/latest.json" does not mention "/articles/alpha.html"

  Scenario: Editing only the body writes only the article
    When the body of the feed article "bravo" is edited and projected
    Then the pages written were exactly "articles/bravo.html"
    And a fresh projection of everything finds nothing to change

  Scenario: Retitling a recent article rewrites the search index and the latest list
    When the feed article "foxtrot" is retitled and projected
    Then the page "_data/search-index.json" mentions "A Different Title"
    And the page "_data/latest.json" mentions "A Different Title"
    And a fresh projection of everything finds nothing to change

  Scenario: Retitling an older article leaves the latest list alone
    When the feed article "bravo" is retitled and projected
    Then the page "_data/search-index.json" mentions "A Different Title"
    And the pages written did not include "_data/latest.json"
    And a fresh projection of everything finds nothing to change

  Scenario: Unpublishing an article removes it from the search index
    When the feed article "bravo" is unpublished and projected
    Then the page "_data/search-index.json" does not mention "/articles/bravo.html"
    And a fresh projection of everything finds nothing to change
