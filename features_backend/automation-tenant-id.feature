Feature: Every automation carries its site's tenant, and rows written without one are stamped once
  The site lists its automations through the Automation `tenantId` index: `papyrus agents apply` and `agents schedules` read it to find each
  agent's automation, and the Today page reads it to show them. The index is sparse, so it holds only rows that carry a `tenantId`. A write by a
  client that has the site's tenant always stamps it, on a create and on an update, with no setting a deploy must turn on first. The writes made
  before that (on Machines on Machines the `rate` and `story-localize` automations, and in fact every row of the other tenant-owned models) carry
  none, so the index lists nothing and `agents apply` called `rate` missing. `papyrus content backfill-tenant-id --tenant ID` stamps those rows
  once: a dry run unless `--apply`, it writes the tenant and nothing else, never touches a row that names another tenant, and a second run writes
  nothing. Until the backfill has run, `agents apply` refuses an agent whose automation exists without a tenant, naming the command, instead of
  failing the deploy on a create of a row that is already there.

  Background:
    Given a site backend whose tenant is "machines-on-machines"

  Scenario: An automation created by an operator carries the site's tenant and is listed by the tenant index
    When an operator creates the automation "digest"
    Then the stored automation "digest" carries the tenant "machines-on-machines"
    And the tenant's automation listing holds "digest"

  Scenario: A new agent's automation created by the deploy is found by the next deploy
    When the build applies the definition "rate"
    Then the stored automation "rate" carries the tenant "machines-on-machines"
    And the build reports "rate" as new
    When the build applies the definition "rate"
    Then the build reports "rate" as unchanged and sent no write

  Scenario: Updating an automation that was written without a tenant stamps it
    Given the site holds the automation "digest" written without a tenant
    When an operator switches off the automation "digest"
    Then the stored automation "digest" carries the tenant "machines-on-machines"
    And the tenant's automation listing holds "digest"

  Scenario: The deploy refuses an agent whose automation exists without a tenant
    Given the site holds the automation "rate" written without a tenant
    When the build applies the definition "rate"
    Then the build is refused naming "rate" and "content backfill-tenant-id"
    And no write was sent

  Scenario: The backfill dry run reports what it would stamp and writes nothing
    Given the site holds the automation "rate" written without a tenant
    And the site holds the message "m-1" written without a tenant
    When the backfill runs for the tenant "machines-on-machines" as a dry run
    Then the backfill would stamp 1 Automation row and 1 Message row
    And no write was sent

  Scenario: The backfill stamps rows without a tenant and leaves other tenants' rows alone
    Given the site holds the automation "rate" written without a tenant
    And the site holds the automation "story-localize" written without a tenant
    And the site holds the automation "elsewhere" owned by the tenant "other-site"
    And the site holds the automation "digest" owned by the tenant "machines-on-machines"
    When the backfill runs for the tenant "machines-on-machines" with --apply
    Then the stored automation "rate" carries the tenant "machines-on-machines"
    And the stored automation "story-localize" carries the tenant "machines-on-machines"
    And the stored automation "elsewhere" carries the tenant "other-site"
    And the backfill wrote 2 rows and left 1 row of another tenant
    And each stamped row's other fields are as they were
    When the backfill runs for the tenant "machines-on-machines" with --apply
    Then no write was sent

  Scenario: After the backfill the deploy finds the agent's automation and creates nothing
    Given the site holds the automation "rate" written without a tenant
    When the backfill runs for the tenant "machines-on-machines" with --apply
    And the build applies the definition "rate"
    Then the build changes "rate" once and creates no second automation
    When the build applies the definition "rate"
    Then the build reports "rate" as unchanged and sent no write

  Scenario: The backfill needs a tenant named on the command line and no tenant in the environment
    When the backfill runs with no tenant
    Then the backfill is refused because it requires a tenant
    When the backfill runs with a tenant set in the environment
    Then the backfill is refused because it reads every row

  Scenario: Every request the automation writes and the backfill send is accepted by the site's GraphQL schema
    Given the site holds the automation "rate" written without a tenant
    When an operator creates the automation "digest"
    And an operator switches off the automation "digest"
    And the backfill runs for the tenant "machines-on-machines" with --apply
    Then the tenant's automation listing holds "rate"
    And every request sent is accepted by the GraphQL schema Amplify generates from the data schema
    And the requests include a create, an update and the tenant listing of Automation
