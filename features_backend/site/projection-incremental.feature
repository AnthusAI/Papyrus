Feature: Incremental projection of a single edit
  Editing one item rewrites that item's pages and only the other pages whose
  content depends on it. A fresh projection of everything after the edit finds
  nothing left to change. Concurrent edits converge, failures are retried, and
  reconcile finds and repairs whatever drifted.

  Background:
    Given a newest-first site of six published articles that has been projected

  Scenario: Retitling an article writes the article, the home page and the archive
    When the feed article "bravo" is retitled and projected
    Then the pages written were exactly "articles/bravo.html, articles/index.html, index.html"
    And a fresh projection of everything finds nothing to change

  Scenario: Editing only the body of an article writes only the article
    When the body of the feed article "bravo" is edited and projected
    Then the pages written were exactly "articles/bravo.html"
    And a fresh projection of everything finds nothing to change

  Scenario: Hiding an article from the feed rewrites the home page but not the archive
    When the feed article "bravo" is hidden from the feed and projected
    Then the pages written were exactly "articles/bravo.html, index.html"
    And the page "index.html" does not mention "bravo"
    And the page "articles/index.html" mentions "bravo"
    And a fresh projection of everything finds nothing to change

  Scenario: Publishing a new article adds it to the home page, the archive and the sitemap
    When a new article "zulu" is published and projected
    Then the pages written were exactly "articles/index.html, articles/zulu.html, index.html, sitemap.xml"
    And a fresh projection of everything finds nothing to change

  Scenario: Unpublishing an article rewrites the listings and the sitemap, then deletes the page
    When the feed article "bravo" is unpublished and projected
    Then the pages written were exactly "articles/index.html, index.html, sitemap.xml"
    And the page "articles/bravo.html" no longer exists
    And the site store wrote "sitemap.xml" before deleting "articles/bravo.html"
    And a fresh projection of everything finds nothing to change

  Scenario: A renamed article leaves a redirect from its old address
    Given the feed article "bravo" is unpublished and projected
    When the feed article "bravo" is republished as "bravo-renamed" and projected
    Then the site redirect store maps "/articles/bravo.html" to "/articles/bravo-renamed.html"
    And the page "articles/bravo.html" no longer exists
    And a fresh projection of everything finds nothing to change

  Scenario: Two concurrent publishes of different articles both appear on the home page and the archive
    When two new articles "yankee" and "xray" are published at the same time
    Then the page "index.html" mentions "yankee"
    And the page "index.html" mentions "xray"
    And the page "articles/index.html" mentions "yankee"
    And the page "articles/index.html" mentions "xray"
    And a fresh projection of everything finds nothing to change

  Scenario: A projection that failed halfway is completed by running it again
    When the feed article "bravo" is retitled and its projection fails after the first write
    And the projection is run again
    Then a fresh projection of everything finds nothing to change

  Scenario: Reconcile repairs a save whose render never ran
    When the feed article "bravo" is retitled but its projection never runs
    Then a dry run of reconcile reports the item "bravo" as stale
    When reconcile runs
    Then a fresh projection of everything finds nothing to change
    And a dry run of reconcile finds no drift

  Scenario: Reconcile removes the page of an article that was unpublished without a render
    When the feed article "bravo" is unpublished but its projection never runs
    And reconcile runs
    Then the page "articles/bravo.html" no longer exists
    And a fresh projection of everything finds nothing to change

  Scenario: Reconcile deletes a page that nothing publishes any more
    Given a stray page "articles/ghost.html" in the site store
    When reconcile runs
    Then the page "articles/ghost.html" no longer exists
