Feature: A site can opt in to targeted invalidation when a story is published
  By default a site's pages age out of the edge cache on their own, and that
  stays until the site's settings say otherwise. A site that sets the cache
  invalidation to "targeted" gets a story's new version at the edge within
  seconds, and pays for it in a way that is easy to predict: publishing or saving
  one story purges exactly the pages that publish wrote, each under both of its
  addresses and with its Markdown twin, and nothing else. In this mode the
  purge never turns into a purge of the whole site, however many pages were
  written. The number of paths in one call is capped by the site's setting;
  above the cap the first paths are purged, the rest are named in the result,
  and the write is still reported as a success. A deploy never purges in this
  mode. Whether the purge worked is its own outcome, never confused with
  whether the page was written.

  Scenario: Publishing one story purges the pages it wrote under both addresses
    Given a site that opted in to targeted invalidation with a cap of 25 paths
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

  Scenario: A site that has not opted in keeps the earlier behaviour
    Given a site that has not set the cache invalidation
    When a publish writes 40 pages
    Then the edge was asked to purge the whole site with one wildcard

  Scenario: A deploy does not purge in targeted mode
    Given a site that opted in to targeted invalidation with a cap of 25 paths
    When the site is rendered by a deploy
    Then the edge was not asked to purge anything
