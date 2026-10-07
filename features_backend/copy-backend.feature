Feature: Copying content from one Papyrus backend to another
  A generic, idempotent copy moves model rows and S3 objects from a source backend
  to a target backend. A dry run reports exactly what an apply would do and writes nothing.

  Scenario: A dry run reports per-model counts and writes nothing
    Given a source backend with 2 items, 1 published item and 3 references
    And an empty target backend
    When I copy the default models and prefixes as a dry run
    Then the plan creates 2 Item rows and 1 PublishedItem row
    And the Reference model is reported as skipped with the reason "not selected"
    And no rows and no objects were written

  Scenario: Applying twice is a no-op the second time
    Given a source backend with 2 items, 1 published item and 3 references
    And an empty target backend
    And I copy the default models and prefixes with apply
    When I copy the default models and prefixes with apply
    Then every selected model is unchanged
    And no rows and no objects were written

  Scenario: Ids, slugs, types, timestamps and the editorial JSON are preserved
    Given a source backend with a videoml item whose editorial JSON has keys in a different order
    And an empty target backend
    When I copy the default models and prefixes with apply
    Then the target item has the same id, slug, type, publishedAt and editorial content

  Scenario: Re-running after the backend reorders JSON keys changes nothing
    Given a source backend with a videoml item whose editorial JSON has keys in a different order
    And an empty target backend
    And I copy the default models and prefixes with apply
    And the target backend returns its JSON fields with reordered keys
    When I copy the default models and prefixes with apply
    Then every selected model is unchanged
    And no rows and no objects were written

  Scenario: Fields the target schema lacks are copied as-is and target-only fields are left alone
    Given a source backend whose items lack the bodyIr field
    And a target backend that has bodyIr and an item already holding a converted bodyIr
    When I copy the default models and prefixes with apply
    Then the item is unchanged and its bodyIr is kept

  Scenario: Identity models are never copied
    Given a source backend with 2 items, 1 published item and 3 references
    And an empty target backend
    When I copy the models "Item,UserProfile" as a dry run
    Then the copy is refused naming "UserProfile"

  Scenario: Rows the target would reject are listed and nothing is written
    Given a source backend with an item missing a field the target requires
    And an empty target backend
    When I copy the default models and prefixes with apply
    Then the plan lists 1 invalid row
    And no rows and no objects were written

  Scenario: Only the media prefix is copied by default and nothing is deleted
    Given a source bucket with objects under media, newsroom and corpora
    And a target bucket with an extra object that the source lacks
    When I copy the default models and prefixes with apply
    Then only the media objects are copied
    And the extra target object is still there
    And the newsroom and corpora prefixes are reported as skipped

  Scenario: Objects that are already identical are not copied again
    Given a source bucket with objects under media, newsroom and corpora
    And a target bucket with an extra object that the source lacks
    And I copy the default models and prefixes with apply
    When I copy the default models and prefixes with apply
    Then no rows and no objects were written

  Scenario: A manifest of per-row hashes and S3 keys is written for both sides
    Given a source backend with 2 items, 1 published item and 3 references
    And an empty target backend
    And I copy the default models and prefixes with apply
    When I write the fidelity manifests
    Then the source and target manifests list the same row hashes for Item
    And the manifests include an S3 key list with sizes
