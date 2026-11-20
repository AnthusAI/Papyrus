Feature: The knowledge models carry their tenant in every key on a shared stack
  A shared stack keeps many tenants' References, corpora, concepts and relations in the same tables, so any lookup
  value that is the same for every tenant today (the feed name "references", "semanticRelations", and so on) would put
  every tenant's rows in one partition. On a shared stack those values start with the tenant ("alpha#references"),
  and a corpus id is "<tenant>.<corpus>", which makes every key that starts with a corpus id (the feed, star,
  medium, content-needed and public keys and the corpus indexes) belong to one tenant with no further change.

  A dedicated stack does not change. One site, one backend, and every key stays byte for byte what it is today, even
  when that stack has a fixed tenant id (several live sites do). There is no dual read, no fallback to the unprefixed
  key and no backfill: the shared stack has no rows yet and the dedicated stacks keep theirs.

  Writers and readers build every such key through one builder per language, in Python
  (src/papyrus_content/tenant_knowledge_keys.py) and TypeScript (lib/tenant-knowledge-keys.ts), and both are tested
  against the same vectors in scripts/fixtures/reference-feed-key-vectors.json. No caller builds a key by hand.
  Nothing here calls AWS.

  Background:
    Given the tenant knowledge key builder

  Scenario: A shared stack prefixes each global key with the tenant
    Given a shared stack
    When tenant "alpha" builds the global keys "references", "references#reviewed", "semanticNodes", "semanticRelations" and "reference-links"
    Then the keys are "alpha#references", "alpha#references#reviewed", "alpha#semanticNodes", "alpha#semanticRelations" and "alpha#reference-links"

  Scenario: A shared stack makes a corpus id unique to its tenant
    Given a shared stack
    When tenant "alpha" builds the corpus id of the corpus key "demo"
    Then the corpus id is "alpha.knowledge-corpus-demo"
    And building it again from that id leaves it as it is
    And the corpus key of that id is "demo"

  Scenario: Two tenants with the same corpus key never share a partition
    Given a shared stack
    When tenant "alpha" and tenant "beta" each build the corpus id of the corpus key "demo"
    Then the two corpus ids differ
    And the two Reference feed keys differ

  Scenario: A dedicated stack keeps every key as it is
    Given a dedicated stack
    When the global keys and the corpus id of the corpus key "demo" are built
    Then the keys are "references", "references#reviewed", "semanticNodes", "semanticRelations" and "reference-links"
    And the corpus id is "knowledge-corpus-demo"

  Scenario: A dedicated stack with a fixed tenant keeps its keys
    Given a dedicated stack whose fixed tenant id is "alpha"
    When the global keys and the corpus id of the corpus key "demo" are built
    Then the keys are "references", "references#reviewed", "semanticNodes", "semanticRelations" and "reference-links"
    And the corpus id is "knowledge-corpus-demo"

  Scenario: A shared-stack key with no tenant is refused
    Given a shared stack
    When a global key is built with no tenant
    Then the build is refused naming the tenant it needs
    And no key is returned

  Scenario: A shared-stack corpus id with no tenant is refused
    Given a shared stack
    When the corpus id of the corpus key "demo" is built with no tenant
    Then the build is refused naming the tenant it needs

  Scenario: A shared stack takes the tenant the process is configured with when the call names none
    Given a shared stack whose process is configured for tenant "alpha"
    When a global key is built with no tenant
    Then the key is "alpha#references"

  Scenario: A new Reference is written under its tenant on a shared stack
    Given a shared stack
    When tenant "alpha" writes a pending Reference from the catalog in the corpus key "demo"
    Then the Reference's corpus id is "alpha.knowledge-corpus-demo"
    And its feed state key starts with "alpha.knowledge-corpus-demo#"
    And its newsroom feed key is "alpha#references"
    And it has no reviewed feed key

  Scenario: An accepted Reference carries the tenant's reviewed feed key
    Given a shared stack
    When tenant "alpha" writes an accepted Reference from the catalog in the corpus key "demo"
    Then its newsroom feed key is "alpha#references"
    And its reviewed feed key is "alpha#references#reviewed"

  Scenario: A new Reference on a dedicated stack with a tenant is written exactly as before
    Given a dedicated stack whose fixed tenant id is "alpha"
    When the stack writes an accepted Reference from the catalog in the corpus key "demo"
    Then the Reference's corpus id is "knowledge-corpus-demo"
    And its newsroom feed key is "references"
    And its reviewed feed key is "references#reviewed"

  Scenario: Each tenant's References page reads only its own rows
    Given a shared stack
    And 5,000 References across 50 tenants
    When "alpha" opens Predictions
    Then the index query's partition starts with an "alpha" corpus id
    And no other tenant's row is read

  Scenario: The same feed key vectors pass in Python and TypeScript
    Given the shared vector file with tenant cases
    When the Python builder runs every tenant case
    Then it produces the keys in the file
    And the TypeScript twin is tested against the same file by npm run test:tenant-knowledge-keys

  Scenario: Reference intake on a shared stack does not need the single-publication declaration
    Given a shared stack
    And an editor session whose token names tenant "alpha"
    When the editor adds a source URL for Reference intake
    Then the intake is accepted
    And the new Reference is in the corpus "alpha.knowledge-corpus-demo"

  Scenario: Reference intake on a dedicated stack with a tenant still needs the declaration
    Given a dedicated stack whose fixed tenant id is "alpha"
    And an editor session with no tenant claim
    When the editor adds a source URL for Reference intake
    Then the intake is refused naming PAPYRUS_SINGLE_PUBLICATION_BACKEND
