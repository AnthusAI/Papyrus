Feature: Guideline documents are stored as a catalog row in the database and one file in S3
  A publication's guidelines for how its stories are written, how its pictures look or how its videos are made are backend data, kept as a guideline
  document. Each kind of guideline (writing, image and video today, others later) and each scope (the publication, or one of its sections) is a
  versioned lineage of the private doctrine record that already holds the mission and the policy. The database row is only the catalog entry: the
  slug, the version, who saved it, when, why, and a hash of the content. The document itself, text included, is one JSON file in S3 attached to that
  version. Every edit makes a new version and the old ones stay, so a draft can always be traced to the exact guidelines it was written with. The
  kinds are data: adding one needs no change to the store or to where files go. This step builds the store; it calls no model and touches no live
  account, and its tests run against an in-memory fake that fails on any table scan.

  Scenario: Saving a writing document stores the text in S3 and only a catalog row in the database
    Given a publication with no guidelines
    When an admin saves a writing document whose body says "Write plainly." with the reason "First guidelines"
    Then exactly one catalog row is stored, for the slug "editorial-doctrine-writing", with an empty body and no metadata
    And exactly one file is stored in S3 as the "doctrine_document" of that row
    And reading the writing guidelines returns the same document, and the row's content hash matches it

  Scenario: Saving an unchanged document makes no new version
    Given a publication with saved writing guidelines
    When an admin saves the same document again naming the current version
    Then no new row and no new file are stored
    And the writing guidelines are still at version 1

  Scenario: Saving against a stale version is refused
    Given a publication with saved writing guidelines
    When an admin saves a change naming a version that is no longer current
    Then the save is refused as stale
    And no new guideline row or file is stored

  Scenario: Every edit makes a new version and the older versions stay
    Given a publication with saved writing guidelines
    When an admin changes the audience to "Engineers" with the reason "Narrowed"
    Then the writing guidelines are at version 2 and say the audience is "Engineers"
    And version 1 can still be read and says the audience is "General readers"
    And the guideline history lists version 2 with the reason "Narrowed" before version 1 with the reason "First guidelines"

  Scenario: A document with problems is refused with every problem named by field
    Given a publication with no guidelines
    When an admin saves a writing document with an empty tone sentence and an unknown field "mystery"
    Then the save is refused as invalid
    And the problems name the fields "tone" and "mystery"
    And no guideline row or file is stored

  Scenario: The repository style profiles are valid writing documents as they are
    Then the style profile of "anthus" validates as a writing document without changes
    And the style profile of "pilobolus" validates as a writing document without changes

  Scenario: Reading never lists or scans a table
    Given a publication with saved writing guidelines
    When the writing guidelines, their history and a section's resolved guidelines are read
    Then every read was a query on the slug index or the attachment owner index

  Scenario: A new kind of guideline needs no change to the store
    Given a new kind "podcast" is registered with a hosts field and no other change
    When an admin saves podcast guidelines for the publication and for the section "weekly"
    Then they are stored under the slugs "editorial-doctrine-podcast" and "desk-doctrine-weekly-podcast"
    And each is one catalog row and one "doctrine_document" file, exactly as for writing guidelines
    And the section's podcast guidelines resolve over the publication's with the hosts of both

  Scenario: Video guidelines are registered with a minimal document
    Given a publication with no guidelines
    When an admin saves a video document whose body says "Cut on motion." with the reason "Experiment"
    Then the video guidelines resolve to that body
    And the stored slug is "editorial-doctrine-video"

  Scenario Outline: The first save of each kind on an empty site creates the row first and then attaches the document
    The upload function only hands out an upload for an Item that already exists, so a first save that sent the file before the row was refused with "Cannot attach payload to
    missing Item" and stored nothing. The row is created first, the document is attached to it, and only then is the version current.
    Given a publication with no guidelines
    When an admin saves a minimal "<kind>" document with the reason "First guidelines"
    Then the row was created before its document was attached
    And the "<kind>" guidelines are at version 1 with their document attached

    Examples:
      | kind         |
      | writing      |
      | video        |
      | byline       |
      | figure-rules |
      | procedure    |

  Scenario: A second save naming the current version attaches its document to its own new row
    Given a publication with saved writing guidelines
    When an admin changes the audience to "Engineers" with the reason "Narrowed"
    Then the row was created before its document was attached
    And the writing guidelines are at version 2 and say the audience is "Engineers"
    And version 1 can still be read and says the audience is "General readers"

  Scenario: A retry after a failed upload finishes the same version and blocks nothing
    When the upload of a first writing document fails
    Then the save is refused with the upload's message
    And the interrupted version is not visible: there are no writing guidelines and no history
    When the same save is made again
    Then the "writing" guidelines are at version 1 with their document attached
    And exactly one catalog row and one file are stored
    When an admin changes the audience to "Engineers" with the reason "Narrowed"
    Then the writing guidelines are at version 2 and say the audience is "Engineers"

  Scenario: A different save after a failed upload takes over the interrupted version
    When the upload of a first writing document fails
    And an admin saves a writing document whose body says "Write plainly." with the reason "Second try"
    Then the "writing" guidelines are at version 1 with their document attached
    And exactly one catalog row and one file are stored
