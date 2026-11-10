Feature: Tenant claims in the sign-in token decide which rows a session can touch
  This is the seed of the adversarial isolation suite (spike PPY-9f3de0, part PPY-867f76). A pre-token-generation
  Lambda adds one claim per role (papyrus_tenant_editor, papyrus_tenant_member and so on), each holding the tenant id the
  session acts for. Item and Reference carry only owner rules that compare the row's tenantId with those claims, and no
  group rules. A session for one tenant must be unable to read or change another tenant's rows, however it asks.

  The scenarios are tagged @sandbox: they need an ampx sandbox in the personal AWS account and two Google test users,
  so the behave run skips them. The same decisions were checked offline, against the resolvers Amplify generates for the
  spike schema, by spikes/tenant-claims-1/run-scenarios.cjs (findings: docs/plans/tenant-claims-spike-1.md).

  @sandbox
  Scenario: A token for alpha cannot touch beta's Item
    Given sandbox users acting for "alpha" and "beta"
    When alpha gets, lists, creates with tenantId beta, updates and deletes beta's Item
    Then every call is denied or returns nothing

  @sandbox
  Scenario: A list through an index at another tenant's key returns nothing
    Given sandbox users acting for "alpha" and "beta"
    When alpha lists Items through the key index at one of beta's keys
    Then the list returns no rows

  @sandbox
  Scenario: A session without a tenant claim can do nothing
    Given a sandbox user whose token carries no tenant claim
    When it gets, lists and creates an Item
    Then every call is denied or returns nothing

  @sandbox
  Scenario: A read-only role cannot write
    Given a sandbox user holding the member role for "alpha"
    When it creates, updates and deletes an "alpha" Item
    Then every call is denied
    And it can still read the "alpha" Item

  @sandbox
  Scenario: An editor cannot move a row to another tenant
    Given an "alpha" editor and an "alpha" Item whose tenantId has a field rule allowing create and read only
    When the editor updates its tenantId to "beta"
    Then the update is denied
