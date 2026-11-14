Feature: A projection lease for each tenant on a shared stack
  A projection takes a lease before it writes a site bucket, so only one
  projection runs at a time. On a dedicated stack the lease is keyed by the
  bucket name, as it always has been, and that holds for a site that happens to
  have a tenant id set. On a shared stack one bucket serves several tenants, so
  the lease is keyed by the bucket and the tenant, and tenants never queue
  behind one another. A projection on a shared stack that names no tenant is
  refused before any lease is taken: the key is never guessed.

  Scenario: Two tenants project at the same time
    Given a shared stack with a lock table
    And alpha holds its projection lease on the bucket
    When beta starts a projection in the same bucket
    Then beta does not wait
    And the lock table holds one lease for alpha and one for beta

  Scenario: A dedicated site's lease is unchanged
    Given a dedicated stack with a lock table
    When a projection lease is built for a site that has the tenant id "alpha"
    And a projection lease is built for a site that has no tenant id
    Then both leases are keyed by the bucket name alone

  Scenario: A shared-stack projection without a tenant is refused
    Given a shared stack with a lock table
    When a projection lease is built with no tenant
    Then the projection is refused because it needs a tenant
    And the lock table holds no lease
