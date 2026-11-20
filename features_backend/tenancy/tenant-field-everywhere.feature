Feature: Every tenant-owned model carries an optional tenantId
  A site that serves several tenants needs to know whose row each one is. Every model a tenant owns has an
  optional tenantId, added without changing any table, key or index, so a dedicated site's rows and calls are
  exactly as they were. A client that has a tenant stamps it on each write, with no setting to turn it on (a site gains the field with its deploy, never by a flag the writer must be told about); a client without one writes nothing
  tenant-shaped. Nothing reads the field yet. The people, sign-in identities and public handles that belong to no
  single tenant stay global.

  Scenario: A tenant client stamps its tenant on every write
    Given a client for tenant "alpha"
    When it creates a Message, an Assignment and a Reference
    Then each row has tenantId "alpha"

  Scenario: A client without a tenant writes exactly as before
    Given a dedicated backend with no tenant configured
    When an editor creates a Message
    Then the row has no tenantId and the call succeeds

  Scenario: Every tenant-owned model declares the field in both schema definitions
    When the schema parity check runs
    Then each of the 56 tenant-owned models has tenantId in the deployed and the typed schema
    And the global identity models UserProfile, UserIdentity and PublicHandleClaim do not
