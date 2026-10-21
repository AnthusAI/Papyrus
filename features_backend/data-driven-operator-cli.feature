@data-driven-cli
Feature: Operating a data-driven publication from the CLI
  A publication whose editorial configuration lives in its backend needs no repo steering
  file. Operators work with the backend's single canonical corpus.

  Scenario: A fresh backend gets its publication from one command
    Given a fresh backend with no canonical corpus
    When the operator runs publication init for key "example-pub" named "Example Publication"
    Then the backend has one canonical corpus "example-pub" named "Example Publication"
    And editorial context resolves the publication "example-pub"

  Scenario: Publication init is idempotent
    Given a backend whose canonical corpus is "example-pub"
    When the operator runs publication init for key "example-pub" named "Example Publication"
    Then the command reports the publication already exists
    And the backend still has one canonical corpus "example-pub"

  Scenario: Publication init refuses to add a second publication
    Given a backend whose canonical corpus is "example-pub"
    When the operator runs publication init for key "other-pub" named "Other"
    Then the command fails saying the backend already serves "example-pub"

  Scenario: A missing publication error names the fix
    Given a fresh backend with no canonical corpus
    When editorial context is requested
    Then the error mentions "papyrus publication init"

  Scenario: A deploy creates the publication from the brand's corpus key
    Given a fresh backend with no canonical corpus
    When a deploy runs with the brand corpus key "example-pub" and name "Example Publication"
    Then the backend has one canonical corpus "example-pub" named "Example Publication"

  Scenario: A deploy leaves a backend that already has another publication alone
    Given a backend whose canonical corpus is "example-pub"
    When a deploy runs with the brand corpus key "other-pub" and name "Other"
    Then the backend still has one canonical corpus "example-pub"

  Scenario: Catalog registration needs no steering file or corpus key
    Given a backend whose canonical corpus is "example-pub"
    And a catalog with an item that has an item_id and an item that has none
    When the operator registers the catalog as pending with no steering file and no corpus key
    Then the registration succeeds
    And both references exist in corpus "example-pub"
    And the computed item_id of the second reference is derived from its source URL

  Scenario: Registration never depends on fetching titles
    Given a backend whose canonical corpus is "example-pub"
    And a catalog with an item that has an item_id and an item that has none
    And the network is unreachable
    When the operator registers the catalog as pending with no steering file and no corpus key
    Then the registration succeeds
    And the registration output has no traceback

  Scenario: A corpus key that is not the publication is refused
    Given a backend whose canonical corpus is "example-pub"
    And a catalog with an item that has an item_id and an item that has none
    When the operator registers the catalog as pending with corpus key "other-pub"
    Then the registration fails with a publication binding mismatch

  Scenario: An item with neither item_id nor URL is named
    Given a backend whose canonical corpus is "example-pub"
    And a catalog with an item that has no item_id and no source URL
    When the operator registers the catalog as pending with no steering file and no corpus key
    Then the registration fails saying catalog item 1 has no item_id and no source_uri

  Scenario: Editor-only intake names the operator alternative
    When a caller without an editor session requests pending reference intake
    Then the refusal mentions "create-from-catalog" and "delegated curation"

  Scenario: A session for another publication suggests the IAM lane
    Given a signed-in session for a different publication endpoint
    When GraphQL headers are requested for this endpoint
    Then the error mentions "PAPYRUS_GRAPHQL_AUTH=iam"
