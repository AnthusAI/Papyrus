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

  Scenario: Each side signs AppSync requests with its own profile
    Given a source session and a target session with different credentials
    When each side signs an AppSync request
    Then the source request is signed with the source access key only
    And the target request is signed with the target access key only

  Scenario: Without profile options the behaviour and the plan are unchanged
    Given a source bucket and a target bucket that differ by one missing media object
    When I copy with the command defaults and apply
    Then the transfer mode is server-side
    And the missing media object was copied with a server-side copy and nothing was streamed
    And the plan reports no source or target account

  Scenario: An account mismatch against --expect-target-account stops before any read or write
    Given a source session in account 111111111111 and a target session in account 222222222222
    When I run copy-backend expecting target account 999999999999 with apply
    Then the command stops naming account 222222222222
    And only the caller identity was read in either session

  Scenario: Matching accounts are printed in the plan
    Given a source session in account 111111111111 and a target session in account 222222222222
    When I run a dry run expecting accounts 111111111111 and 222222222222
    Then the plan reports source account 111111111111 and target account 222222222222

  Scenario: A stream copy preserves key, size, content type, metadata and the ETag of 8 MiB multipart sources
    Given a cross-account source bucket with a small object, a 20 MiB object uploaded in 8 MiB parts and a 12 MiB single upload
    And an empty cross-account target bucket
    When I copy the objects in stream mode
    Then every key exists in the target with the same size, content type, cache control and metadata
    And the ETags of all three objects equal the source ETags
    And the 20 MiB object was uploaded in 3 parts of at most 8 MiB

  Scenario: Re-running a stream copy transfers nothing
    Given a cross-account source bucket with a small object, a 20 MiB object uploaded in 8 MiB parts and a 12 MiB single upload
    And an empty cross-account target bucket
    And I copy the objects in stream mode
    When I copy the objects in stream mode
    Then no object is read from the source and nothing is written to the target

  Scenario: The source session never calls a write operation
    Given a cross-account source bucket with a small object, a 20 MiB object uploaded in 8 MiB parts and a 12 MiB single upload
    And an empty cross-account target bucket
    When I copy the objects in stream mode
    Then the source client received only list, head and get calls
    And a write attempted through the source store is refused

  Scenario: N workers copy every object exactly once and a failed key is reported, not hidden
    Given a source bucket with 40 small objects under media where one key cannot be copied
    And an empty target backend
    When I copy with 8 workers and apply
    Then every copyable object was copied exactly once
    And the plan reports 1 error naming the failed key
    And the other 39 objects are present in the target

  Scenario: Stream copies hold at most the memory budget at once
    Given a cross-account source bucket with a small object, a 20 MiB object uploaded in 8 MiB parts and a 12 MiB single upload
    And an empty cross-account target bucket
    When I copy the objects in stream mode with 4 workers and a 16 MiB memory budget
    Then no more than 16 MiB were held in memory at once

  Scenario: Rows with a null composite-index sort-key field are written with the app's neutral default
    Given a source backend with 3 messages of which 2 leave responseStatus null
    And a target backend whose Message index rejects a null responseStatus
    When I copy the Message model with apply
    Then all 3 Message rows were written
    And the 2 rows that had a null responseStatus now carry COMPLETED
    And the business fields and the null responseTarget of every row are unchanged
    And the plan reports 2 Message rows given key-field defaults

  Scenario: A dry run predicts the key-field defaults and does not fail
    Given a source backend with 3 messages of which 2 leave responseStatus null
    And a target backend whose Message index rejects a null responseStatus
    When I copy the Message model as a dry run
    Then the plan is ok and lists 0 invalid rows
    And the plan reports 2 Message rows given key-field defaults
    And the printed table names the Message key-field defaults
    And no rows and no objects were written

  Scenario: Re-running after key-field defaults were applied changes nothing
    Given a source backend with 3 messages of which 2 leave responseStatus null
    And a target backend whose Message index rejects a null responseStatus
    And I copy the Message model with apply
    When I copy the Message model with apply
    Then every selected model is unchanged
    And no rows and no objects were written

  Scenario: An explicit key-field default overrides the built-in one
    Given a source backend with 3 messages of which 2 leave responseStatus null
    And a target backend whose Message index rejects a null responseStatus
    When I copy the Message model with apply and the key-field default "Message.responseStatus=ARCHIVED"
    Then the 2 rows that had a null responseStatus now carry ARCHIVED

  Scenario: A null composite sort-key field without a default is listed as invalid
    Given a source backend with a Ticket whose composite sort-key field lane is null
    And a target backend whose Ticket index rejects a null lane
    When I copy the Ticket model with apply
    Then the plan lists the Ticket row as invalid with "null-composite-sort-key:lane"
    And no rows and no objects were written

  Scenario: An exact S3 key is selected without its look-alike neighbours
    Given a source bucket with the corpora keys steering, steering backup and another file
    And a target bucket with an extra object that the source lacks
    When I copy with the exact S3 key "corpora/papyrus-steering.yml" and no prefixes
    Then only the corpora/papyrus-steering.yml object is copied

  Scenario: An exact S3 key that the source lacks is an error
    Given a source bucket with the corpora keys steering, steering backup and another file
    And a target bucket with an extra object that the source lacks
    When I copy with the exact S3 key "corpora/missing.yml" and no prefixes
    Then the plan reports an error naming "corpora/missing.yml"
    And no rows and no objects were written

  Scenario: Exact keys and prefixes combine and the media default applies only when neither is given
    When I resolve the S3 selection for prefixes "newsroom/" and keys "corpora/papyrus-steering.yml"
    Then the prefixes are "newsroom/" and the keys are "corpora/papyrus-steering.yml"
    When I resolve the S3 selection for no prefixes option and keys "corpora/papyrus-steering.yml"
    Then there are no prefixes and the keys are "corpora/papyrus-steering.yml"
    When I resolve the S3 selection for no prefixes option and no keys option
    Then the prefixes are "media/" and there are no keys
