Feature: Tenant records
  A shared stack needs to know which tenants exist, who belongs to each and which hostnames each serves. Three new
  tables hold that: Tenant (one row per site, owned by a Prospectus Account), TenantMembership (one row per person and
  tenant, found by the person's sign-in id) and TenantDomain (one row per hostname). They sit in an optional model
  group named "tenancy", so a dedicated site can leave them out of a first deploy. Nothing reads or writes them yet;
  the token Lambda and provisioning come next. A platform operator writes the rows, a tenant's admin reads its own,
  and the tenant-claims and provisioning functions reach them with their own IAM grants.

  Scenario: A tenant's members are found without a scan
    Given 3 tenants with 5 members each
    When the token Lambda looks up Ada's memberships
    Then it makes one query on the userSub index and reads only Ada's rows

  Scenario: A hostname belongs to one tenant
    Given "alpha.apyr.us" is a TenantDomain of "alpha"
    When "beta" tries to add "alpha.apyr.us"
    Then it is refused

  Scenario: The tenancy models can be left out of a first deploy
    When the tenancy model group is excluded
    Then Tenant, TenantMembership and TenantDomain are not in the schema
    And every other model is

  Scenario: The deployed and typed schemas agree
    When the schema parity check runs
    Then Tenant, TenantMembership and TenantDomain have the same fields and indexes in both files
    And each of them has its indexes on a new table only, with no index added to an existing table
