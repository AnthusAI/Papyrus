Feature: One projection of a publication at a time
  A deploy-time reprojection, a papyrus command-line projection, a publish-time
  item projection and a scheduled cloud run all write the same site bucket.
  Each takes a lease on the publication, a single item in a shared DynamoDB
  table keyed by the site bucket name, before it writes anything, and gives it
  back when it finishes, whether it succeeded or failed. A lease carries its
  owner and an expiry, so a crashed holder cannot block the publication for
  longer than the time to live. A projection that finds the lease held waits,
  retrying with exponential backoff, for a bounded time and then fails with a
  message that names the holder. Without a lock table, or when nothing live is
  written, there is no lease and projection behaves as it always did.

  Background:
    Given a lock table and a site of three published articles that has been projected

  Scenario: A projection takes the lease and releases it when it finishes
    When the site is projected under the lease and the lease is observed while it runs
    Then the lease for the site bucket was held by the projection while it ran
    And the lease no longer exists

  Scenario: The lease is released when the projection fails
    Given the projector fails while rendering
    When the site is projected under the lease
    Then the leased projection failed with "renderer broke"
    And the lease no longer exists

  Scenario: The lease is released when the deletion guard refuses the projection
    When the site configuration stops placing the article "seed-1" and the site is projected under the lease with the deletion guard on
    Then the leased projection failed with "Refusing to delete"
    And the lease no longer exists

  Scenario: A projection waits for a lease held by another owner and proceeds once it is released
    Given another owner holds the lease
    When the site is projected under the lease and the other owner releases the lease after 3 retries
    Then the projection waited 1, 2 and 4 seconds before it took the lease
    And the leased projection finished
    And the lease no longer exists

  Scenario: A lease held beyond the wait limit fails the projection and writes nothing
    Given another owner holds the lease
    When the site is projected under the lease with a wait limit of 10 seconds
    Then the leased projection failed with "Projection lease for site-bucket is held by other-owner"
    And the failure tells the operator how to clear the lease
    And the site store is untouched by the leased projection
    And the other owner still holds the lease

  Scenario: A stale lease is taken over without waiting
    Given another owner holds a lease that expired
    When the site is projected under the lease
    Then the leased projection finished without waiting
    And the lease no longer exists

  Scenario: Two concurrent projections of the same publication never run at the same time
    When two projections of the same publication start together
    Then both projections finished
    And their runs did not overlap

  Scenario: Different publications do not block each other
    Given another owner holds the lease of a different publication
    When the site is projected under the lease
    Then the leased projection finished without waiting
    And the other publication is still leased by the other owner

  Scenario: No lock table configured means no lease
    When a projection context is built where no lock table is configured
    Then the context has no lease
    And the whole site can be projected with no lease

  Scenario: A local-directory projection takes no lease
    When a context is built for projecting to a local directory while a lock table is configured
    Then the context has no lease
    And projecting the whole site with that context leaves the lock table empty

  Scenario: The deploy render takes the lease
    When the deploy render runs and the lease is observed while it runs
    Then the lease for the site bucket was held by the projection while it ran
    And the lease no longer exists

  Scenario: Snapshot re-projection takes the lease
    When a knowledge snapshot with re-projection runs and the lease is observed while it runs
    Then the lease for the site bucket was held by the projection while it ran
    And the lease no longer exists

  Scenario: A dry-run reconcile is read-only and takes no lease
    Given another owner holds the lease
    When the site is reconciled as a dry run
    Then the leased projection finished without waiting
    And the other owner still holds the lease
