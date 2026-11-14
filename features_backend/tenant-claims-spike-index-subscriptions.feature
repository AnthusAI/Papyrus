# PPY-f4d892 (part 2 of the access-rule spike PPY-9f3de0). Sibling part PPY-867f76 owns features_backend/tenant-claims-spike.feature;
# the two files merge into that one name when the spike closes. Driver: spikes/tenant-claims-2/run-spike.ts (sandbox only).
# The scenarios are tagged @sandbox: they need an ampx sandbox in the personal AWS account, so the behave run skips them (features_backend/environment.py), as for part 1.
# Static evidence instead: docs/plans/tenant-claims-spike-2-findings.md.
Feature: Tenant claims on index lists, subscriptions and immutable tenantId

  Background:
    Given a sandbox with tenants "alpha" and "beta"
    And an editor session acting for "alpha" and an editor session acting for "beta"

  @sandbox
  Scenario: An index list returns full pages for the caller's tenant
    Given 300 alpha and 300 beta References under prefixed keys
    When alpha lists 100 at a time through the index
    Then each page holds 100 alpha rows and no beta row

  @sandbox
  Scenario: An index list under another tenant's prefix returns nothing
    Given 300 alpha and 300 beta References under prefixed keys
    When alpha lists through the index with the key "beta#reference"
    Then no row is returned

  @sandbox
  Scenario: An index whose key is not tenant-prefixed returns short pages
    Given 300 alpha and 300 beta References that share one index key
    When alpha lists 100 at a time through that index
    Then the pages hold fewer than 100 rows each and hold no beta row

  @sandbox
  Scenario: A subscription only delivers the caller's tenant
    Given an alpha editor listening for created References
    When a beta editor, an alpha editor and a beta editor each create a Reference
    Then the listener receives exactly one event, for "alpha"

  @sandbox
  Scenario: tenantId cannot be moved after create
    Given an alpha Reference
    When the alpha editor updates its tenantId to "beta"
    Then the update is denied naming the field
    And updating its tenantKey to "beta#reference" is denied too

  @sandbox
  Scenario: Access-token claims are what the data client sends
    Given an editor session acting for "alpha" on a user pool with the Essentials plan
    Then the access token carries "papyrus_tenant_editor" equal to "alpha"
    And a call authorised with that access token succeeds
