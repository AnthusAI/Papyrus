Feature: Every table can list one tenant's rows without reading the others
  Export, deletion and usage reporting each need every row one tenant owns, table by table. Reading a whole table and
  keeping the tenant's rows costs one read for every row of every tenant, which grows with the number of tenants, not
  with the tenant being exported. So every table needs a way to list one tenant's rows directly.

  Most tables already have one: an index whose partition is a status, a kind or a constant lists a tenant once that
  value carries the tenant prefix, and References are listed corpus by corpus through the tenant's own corpora. The
  tenant key inventory (docs/tenant-key-inventory.md) names the tables that have none, either because they have no
  index at all (ReaderVote, ReviewRequest, Automation and others) or because every index they have leaves rows out
  (Item's indexes sort on fields an idea does not have yet). Each of those tables gets one sparse index partitioned
  on tenantId and sorted by id. Item's waits one release: the release this lands in already gives Item its language
  group index, and a table gains one index per release (follow-up PPY-e958b5). The tenant client reads a tenant's rows through it with one paged Query
  (`list_tenant_rows`), never a Scan. The index holds only rows that carry a tenantId, so a listing is complete once
  the tenantId backfill (PPY-8f9462) has stamped every row.

  DynamoDB creates one index per table in one update, so a table may gain only one index in a release. The GSI ledger
  compares every schema source (the core schema and each plugin's and function's schema) with the last release and
  refuses a table that gains two.

  Scenario: Exporting a tenant reads no other tenant's rows
    Given 50 tenants with ReaderVote rows
    When the tenant "alpha" is exported
    Then ReaderVote is read through the tenantId index and the read count equals alpha's rows

  Scenario: A table never gains two indexes in one release
    Given the released reader steering schema, before ReaderVote had a tenantId index
    When this change's reader steering schema is compared with it
    Then the ledger passes and places ReaderVote's tenantId index in release 1
    When a second new ReaderVote index is added to the same release
    Then the ledger fails naming ReaderVote and both of its new indexes
