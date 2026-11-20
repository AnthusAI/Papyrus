Feature: Publishing purges exactly the pages it wrote, by default
  Every site invalidates in "targeted" mode unless its settings say otherwise,
  so that no site pays for a purge of the whole site. Publishing or saving one
  story purges exactly the pages that publish wrote, each under both of its
  addresses and with its Markdown twin, and nothing else, and the story's own
  pages are purged before the index pages that list it. The purge never turns
  into a purge of the whole site, however many pages were written. The number of
  paths in one call is capped by the site's setting; above the cap the first
  paths are purged, the rest are named in the result, and the write is still
  reported as a success. A deploy, a whole-site render and the follow-up render
  of other pages never purge. A site can switch the purge off, or explicitly ask
  for the old behaviour of purging the whole site with one wildcard, which is
  billable and discouraged. Whether the purge worked is its own outcome, never
  confused with whether the page was written.

  Scenario: Publishing one story purges the pages it wrote under both addresses
    Given a site that has not set the cache invalidation
    When one story is published with a new version
    Then the edge was asked to purge exactly the paths of the pages that publish wrote
    And no purged path is a wildcard
    And the publish reports the pages written and the paths purged as separate outcomes

  Scenario: A large publish never becomes a wildcard
    Given a site that opted in to targeted invalidation with a cap of 3 paths
    When a publish writes 40 pages
    Then the edge was asked to purge 3 paths
    And no purged path is a wildcard
    And the publish names the paths that were not purged
    And the pages are reported as written, not as a failed write

  Scenario: An unset site purges exactly the pages, capped at the default of 25
    Given a site that has not set the cache invalidation
    When a publish writes 40 pages
    Then the edge was asked to purge 25 paths
    And no purged path is a wildcard

  Scenario: The story's own pages are purged first when the purge is capped
    Given a site that has not set the cache invalidation
    When a publish writes the story page and 40 listing pages
    Then the first paths purged are the story page and its twin

  Scenario: A site that asks for the old behaviour purges the whole site with one wildcard
    Given a site that set the cache invalidation to "all"
    When a publish writes 40 pages
    Then the edge was asked to purge the whole site with one wildcard

  Scenario: A deploy does not purge by default
    Given a site that has not set the cache invalidation
    When the site is rendered by a deploy
    Then the edge was not asked to purge anything

  Scenario: A whole-site render does not purge by default
    Given a site that has not set the cache invalidation
    When the whole site is rendered
    Then the edge was not asked to purge anything
