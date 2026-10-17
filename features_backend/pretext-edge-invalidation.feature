Feature: A Pretext publish purges our CloudFront copies of the revalidated pages
  A Pretext reader refreshes its own cache when an item is published, but the
  CloudFront distribution in front of it keeps its copy until the shared-cache
  lifetime ends. The publish asks CloudFront to forget exactly the paths the
  reader says it refreshed, on every distribution the site names.

  Scenario: The revalidated paths are invalidated on each configured distribution
    Given a Pretext reader that revalidated "/articles/my-post" and "/archive"
    And the site names the distributions "EONE" and "ETWO"
    When the publish purges the edge
    Then distribution "EONE" was invalidated for "/articles/my-post" and "/archive"
    And distribution "ETWO" was invalidated for "/articles/my-post" and "/archive"
    And the purge succeeded

  Scenario: A reader that refreshed nothing purges nothing
    Given a Pretext reader that revalidated nothing
    And the site names the distributions "EONE"
    When the publish purges the edge
    Then no invalidation was requested
    And the purge succeeded

  Scenario: One distribution failing does not stop the others and is reported
    Given a Pretext reader that revalidated "/archive"
    And the site names the distributions "EBAD" and "EGOOD"
    And distribution "EBAD" rejects invalidations
    When the publish purges the edge
    Then distribution "EGOOD" was invalidated for "/archive"
    And the purge reported a failure for "EBAD"

  Scenario: A wildcard path from the reader is refused
    Given a Pretext reader that revalidated "/*"
    And the site names the distributions "EONE"
    When the publish purges the edge
    Then no invalidation was requested
    And the purge reported a failure for "EONE"
