Feature: Each site's JSON writing guidelines are converted to guideline files once, with the resolved result unchanged
  Before this change a site's writing guidelines were one JSON document for the publication, one for each section and one for each language overlay. A command,
  papyrus guidelines convert, converts them. It is a dry run unless it is given --apply, and it never runs by itself: for every lineage it writes the document as its
  fixed-name files, reads those files back, and refuses the lineage unless the document it reads back is the document it started with. Only an admin who is a person
  may apply it, each lineage is saved as its next version naming the version it replaces, and running it again converts nothing. The old versions stay as history and
  say they were saved before guidelines became files; nothing else reads the JSON shape, and the conversion module is deleted once the last site has been converted.
  These scenarios run on fixtures in memory and touch no live site.

  Background:
    Given a site whose writing guidelines are still JSON documents for the publication, the section "news" and the language "es"

  Scenario: A dry run reports every lineage and stores nothing
    When the conversion is run without --apply
    Then it reports the publication, the section "news" and the language "es" as ready with the resolved result unchanged
    And the conversion stored nothing new

  Scenario: Applying converts every lineage and the resolved guidelines are the same
    When the conversion is run with --apply by an admin
    Then it reports each lineage as converted
    And each lineage is at version 2 and is stored as files
    And the guidelines resolved for the section "news" and for the language "es" are the same documents as before

  Scenario: Running the conversion again changes nothing
    Given the conversion has been applied
    When the conversion is run with --apply by an admin
    Then it reports each lineage as already files
    And the conversion stored nothing new

  Scenario: Only an admin applies it
    When the conversion is run with --apply by an editor
    Then it is refused as not authorised and nothing is stored

  Scenario: A document that does not read back the same is refused and left alone
    Given the publication's JSON document has a body with Windows line endings
    When the conversion is run with --apply by an admin
    Then the publication is reported as refused naming the field "bodyMarkus"
    And the publication's current version is still its JSON document at version 2

  Scenario: An old version is history only once converted
    Given the conversion has been applied
    When version 1 of the publication's writing guidelines is read
    Then it is refused as saved before guidelines became files
