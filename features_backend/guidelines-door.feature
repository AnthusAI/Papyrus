Feature: Guidelines are read and saved through the site's data API door
  A site's guidelines (writing, image, video, and any kind added later) are read and saved through two fields on the site's data API: guidelinesRead for
  operations that only read and guidelinesWrite for operations that save. Editors and admins may use the door. The image-service function behind it takes who
  is asking from the identity the API verified and never from the request; it runs the same operations the command line runs, and records the person's name on
  every version. Only an admin may save. Adding, changing or removing a binding constraint needs an admin who is a person, so a caller that declares itself an
  agent is refused even with an admin's session. A write can be repeated safely with its request id. The tests run against an in-memory backend and in-memory
  files that fail on any table scan; no model, no AWS and no live data is touched.

  Scenario: An admin saves writing guidelines through the door
    Given a door onto a publication with no guidelines
    When an admin saves writing guidelines naming "none" as the version they replace, with the reason "First guidelines"
    Then the door answers with version 1 of the writing guidelines
    And the version records "Ada Admin" as the person who saved it
    And the catalog row holds no text and the document is stored as one file
    And an editor reading the writing guidelines gets the document that was saved

  Scenario: An editor can read but not save guidelines
    Given a door onto a publication with saved writing guidelines
    When an editor reads the writing guidelines through the door
    Then the door answers with the saved document
    When an editor tries to save a change to the audience
    Then the door answers that the caller is not authorised and nothing new is stored

  Scenario: Whether the caller is an admin comes from their group, not from anything they send
    Given a door onto a publication with saved writing guidelines
    When an editor sends a save that claims to come from an admin
    Then the door refuses the request because the input has no such property
    And a signed-in reader is not admitted to either door

  Scenario: An agent cannot change a binding constraint even with an admin's session
    Given a door onto a publication with saved writing guidelines
    When an agent in an admin's session asks to drop the writing binding constraint
    Then the guidelines door answers that a person is required and nothing new is stored
    When that agent changes only the tone
    Then the door saves version 2 and the history says an agent saved it
    When an admin who is a person drops the binding constraint
    Then the door saves version 3

  Scenario: Repeating a write with the same request id returns the first answer
    Given a door onto a publication with saved writing guidelines
    When an admin saves an audience change twice with the same request id
    Then both guideline answers name version 2 and only one new version was stored
    And the same guideline change with a different request id is refused as stale

  Scenario: The read door refuses a write operation, and each door refuses the other family's operations
    Given a door onto a publication with saved writing guidelines
    When an editor tries to save guidelines through the read door
    Then the guidelines door says to use guidelinesWrite
    When an admin tries to read guidelines through the write door
    Then the guidelines door says to use guidelinesRead
    When an editor asks the image door for guidelines
    Then the guidelines door says to use guidelinesRead
    When an editor asks the guidelines door for an image operation
    Then the guidelines door says to use imageRead

  Scenario: A stale version, an invalid document and an unchanged document save nothing
    Given a door onto a publication with saved writing guidelines
    When an admin saves naming a version that is no longer current
    Then the door answers that the guidelines have changed and nothing new is stored
    When an admin saves a document with an empty tone sentence and an unknown field "mystery"
    Then the door lists the problems on the fields "tone" and "mystery" and nothing new is stored
    When an admin saves the document that is already current
    Then the door answers that nothing changed and the guidelines stay at version 1

  Scenario: Video guidelines use the same door, and an unknown kind is refused with the known ones
    Given a door onto a publication with no guidelines
    When an admin saves video guidelines naming "none" as the version they replace
    Then an editor reading the video guidelines gets the saved document
    When an editor reads guidelines of the kind "poetry"
    Then the door answers that the kind is unknown and the known kinds include "image", "video" and "writing"

  Scenario: A section's guidelines are resolved over the publication's with the source of every field
    Given a door onto a publication with saved writing guidelines
    And a section "security" with its own tone and audience
    When an editor resolves the writing guidelines for the section "security"
    Then the tone has the publication's sentence and then the section's
    And the field sources differ for the tone and the binding constraints

  Scenario: Image guidelines are the image profile operations under the same names
    Given a guidelines door onto a publication with a saved style profile
    When an editor reads the image guidelines through the guidelines door
    Then the door answers with the style profile as the document
    And resolving image guidelines points at the image profile resolver

  Scenario: The door's files stay under the item payload prefix
    Given the door's S3 files
    When a guideline file is written and read back
    Then the object and the attachment row are written under the item payload prefix
    And a path outside that prefix is refused before S3 is asked
