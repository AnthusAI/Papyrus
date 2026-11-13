Feature: Rounds and pictures are kept in the backend as catalog rows and private files, read only by index
  Generated pictures need a home that survives the command that made them. A round and each of its candidates are private records in the backend: a catalog row
  in the database that holds no text, and the record itself as a file in private storage, in the same way the guidelines are kept. A picture is a private
  file that nobody can read from the public site until it is applied. No table is scanned and no new index is needed: a round or a candidate is found by its
  name, a round's candidates by their round, a repeated request by its note and the day's spending by the day. Discarding deletes the private file and keeps the
  record. Applying a picture copies it into the site's media, records on the picture that it was generated and by which model and guidelines version, gives it
  no credit line, and saves the Story's next draft version; it never publishes. Spending is still refused unless the site's image guidelines approve it. The
  specs use an in-memory backend, in-memory storage and a fake provider; nothing reaches AWS or a real provider.

  Scenario: A round is a catalog row with no text and a record file, found again from a fresh store
    Given an image publication "ours" whose guidelines approve spending on "gpt-image-2.5-flare"
    And the site keeps rounds in the backend
    And a fake image provider
    When a person generates a set of 2 "cover" pictures of type "cover-illustration" with no Story and no section with the brief "A locked filing cabinet"
    Then the backend holds one round row and 2 candidate rows of private type with no body text
    And the prompt and the brief are in record files and not in any row
    And a fresh store reads the round back with 2 ready candidates
    And every read the stores made was by a named index

  Scenario: Pictures are private files, never media, until applied
    Given an image publication "ours" whose guidelines approve spending on "gpt-image-2.5-flare"
    And the site keeps rounds in the backend
    And a fake image provider
    When a person generates a "cover" picture of type "cover-illustration" with no Story and no section with the brief "A locked filing cabinet"
    Then the picture file is stored under the newsroom's private payload prefix
    And no object was written to the site's media

  Scenario: The day's spend and a repeated request are found by index from a fresh store
    Given an image publication "ours" whose guidelines approve spending on "gpt-image-2.5-flare" with a daily ceiling of 0.04 dollars
    And the section "security" has an image document that adds the guidance "Keep it quiet." and avoids "keys"
    And the site keeps rounds in the backend
    And a fake image provider
    When a person generates as request "same" a "cover" picture of type "cover-illustration" for the section "security" with the brief "Section art"
    And a person generates as request "same" a "cover" picture of type "cover-illustration" for the section "security" with the brief "Section art"
    Then the provider was called once
    And a fresh store says 0.03032 dollars were spent on the day
    When a person generates a set of 2 "cover" pictures of type "cover-illustration" with no Story and no section with the brief "More"
    Then candidate 1 of the latest round is "ready"
    And candidate 2 of the latest round failed with the error "spend_ceiling_exceeded"

  Scenario: Discarding deletes the private file and keeps the record
    Given an image publication "ours" whose guidelines approve spending on "gpt-image-2.5-flare"
    And the site keeps rounds in the backend
    And a fake image provider
    When a person generates a "cover" picture of type "cover-illustration" with no Story and no section with the brief "A locked filing cabinet"
    And a person discards candidate 1 because "Too busy"
    Then the stored object was deleted and the file can no longer be read
    And the candidate's record is still there as "rejected" with its earlier version kept

  Scenario: Applying copies the picture into media, records where it came from and saves a draft that is not published
    Given an image publication "ours" whose guidelines approve spending on "gpt-image-2.5-flare"
    And a Story "story-1" in each publication
    And the site keeps rounds in the backend
    And a fake image provider
    When a person generates a "cover" picture of type "cover-illustration" for the Story "story-1" with the brief "A locked filing cabinet"
    And a person applies candidate 1 to the Story "story-1" as the cover
    Then the apply succeeds as "human-verified"
    And the picture was copied to the site's media under "media/assets/story-1/"
    And the Story's new version is a draft that starts with the picture and has the cover set
    And the picture's media record says it was generated, by which model, and has no credit
    And the earlier Story version is superseded and nothing was published

  Scenario: The default handlers refuse an unconfigured site before touching the store or the provider
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    And a fake image provider
    When a person generates through the default handlers a "cover" picture of type "cover-illustration" with no Story and no section with the brief "A locked filing cabinet"
    Then generation is refused with "generation_not_configured" because "no_models"
    And the provider was not called
    And the backend wrote nothing
