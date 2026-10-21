Feature: The standard Markus front end
  A site that declares a "site" object in projection.json gets a complete static front end from Papyrus:
  pages, listings, tags, sitemap, robots, a 404 page, RSS and Atom feeds and the head tags search and social
  cards need. Sections are optional: a site without them is the simple case. A site without the object is
  untouched.

  Scenario: A site with only a name is a working site without sections
    Given a standard site with only a name and the flat fixture content
    Then the standard site has these pages: "index.html, orchids.html, about.html, archive/index.html, 404.html, sitemap.xml, robots.txt, feed.xml, atom.xml"
    And no standard page lives under a section base
    And the standard page "robots.txt" says "Sitemap: https://example.org/sitemap.xml"

  Scenario: A site with sections and directory URLs lists each section once and leaves link-only items without pages
    Given the standard sectioned fixture site
    Then the standard site has these pages: "essays/index.html, essays/slow-water/index.html, notes/index.html, links/index.html, tags/index.html"
    And the standard site lacks these pages: "links/map-archive/index.html, empty/index.html"
    And the standard page "sitemap-index.xml" says "sitemap-0.xml"

  Scenario: Editing only the body writes only the article
    Given the standard flat fixture site
    When the body of the standard item "item-orchids" is edited and projected
    Then the standard site wrote exactly "orchids.html"

  Scenario: Retitling an article rewrites its listings, tag pages, feeds and search data
    Given the standard flat fixture site
    When the title of the standard item "item-orchids" is changed to "Orchids, Revised" and projected
    Then the standard site wrote at least "orchids.html, archive/page/2/index.html, feed.xml, atom.xml, _data/search-index.json"
    And the standard page "atom.xml" says "Orchids, Revised"
    And a fresh standard projection finds the same pages

  Scenario: Unpublishing withdraws an article from the listings, the sitemap and both feeds
    Given the standard flat fixture site
    When the standard item "item-moss" is unpublished and projected
    Then the standard page "feed.xml" does not say "moss.html"
    And the standard page "atom.xml" does not say "moss.html"
    And the standard page "sitemap.xml" does not say "moss.html"
    And the standard page "archive/page/2/index.html" does not say "moss.html"
    And the standard site lacks these pages: "moss.html"

  Scenario: An origin that is not production is guarded
    Given the standard flat fixture site served from "https://staging.example.org"
    Then the standard page "robots.txt" says "Disallow: /"
    And the standard page "orchids.html" says "noindex, nofollow"
    And the standard page "orchids.html" says "https://staging.example.org/orchids.html"

  Scenario: Pattern redirects are data for the edge function
    Given the standard sectioned fixture site
    Then the standard edge rules send "/blog/slow-water/" to "/essays/slow-water/"
    And the standard edge rules send "/essays/slow-water.html" to "/essays/slow-water/"
    And the standard edge rules leave "/404.html" alone

  Scenario: Without a site object the bare projector is used
    Given a static directory whose projection.json has no site object
    Then the standard projector choice is the bare Markus projector

  Scenario: Dates written out in words order entries like ISO dates
    Then the standard entry date of "Sunday, September 6, 2026" is "2026-09-06"
    And the standard entry date of "'September 6, 2026'" is "2026-09-06"
    And the standard entry date of "2026-09-06" is "2026-09-06"
    And the standard entry date of "last Tuesday" is blank
