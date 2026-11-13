Feature: One generated table says which keys are global and which tables can list a tenant
  Moving many tenants onto one set of tables (PPY-1ce06f and the key tasks that follow) needs one fact about every
  model: what the partition value of each of its indexes is. A value that already starts with the tenant is safe. A
  value that starts with a corpus id is safe once corpus ids are unique across tenants. A value that is another
  record's id is safe because ids are unique, but it cannot list a whole tenant. A constant, an enum, a slug or a
  person is shared by every tenant, so it must be prefixed before it is safe. The table also says, for every model,
  whether at least one dense index can list every row of one tenant once its value is prefixed, and that column
  decides which tables need a tenantId index.

  scripts/generate-tenant-key-inventory.ts writes docs/tenant-key-inventory.md from the same reading of the deployed
  schema that the tenant isolation case table uses (amplify/data/schema.ts plus every plugin's models). How each
  partition field is classified is declared once, in scripts/lib/tenant-key-classes.ts, and the check compares that
  declaration with the schema. Nothing here calls AWS.

  Scenario: The inventory is current
    Given schema.ts changes an index
    When the inventory check runs in CI
    Then the inventory check fails naming the model and the index
    And the failure names the command that regenerates the inventory

  Scenario: The committed inventory passes
    When the inventory check runs in CI
    Then the inventory check passes

  Scenario: A new index must be classified
    Given an index is added whose partition field is not classified
    When the inventory check runs in CI
    Then the inventory check fails naming the model and the index
    And the failure says the partition field is not classified

  Scenario: A classification for a field nothing partitions on any more fails
    Given a field is classified that no index partitions on
    When the inventory check runs in CI
    Then the inventory check fails naming the field

  Scenario: The inventory covers every model and classes its partition keys
    When the inventory is read
    Then every model of the schema has a row
    And the five tenant models carry tenant-prefixed partition keys where the tenancy code prefixes them
    And the reference feed keys are corpus-prefixed and the record ids are record-id
    And the global models UserProfile, UserIdentity and PublicHandleClaim are listed as global by design
    And the models that need a tenantId index are listed
