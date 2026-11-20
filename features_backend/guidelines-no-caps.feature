Feature: A set of guideline files has no made-up size or count limit
  A site's guideline files are stored one file at a time, each in its own object in the site's file store, with the catalog row holding only a hash over the
  whole set. Nothing in that design needs a count or a size chosen in advance, so none is applied: a set of any number of files and a file of any length is
  stored whole, resolved whole and exported byte for byte, and a save is refused only for a real fault in a file (a path outside a guideline folder, a rule
  that is not valid, a scope or language that is not the set's own). Reading a version lists its files from the database one page at a time until the last
  page, so a set larger than any one page is read whole; if a page were ever lost the hash over the set would fail loudly and the read would be refused,
  never answered with some of the files.

  Background:
    Given a site with no writing guidelines yet

  Scenario: A set of more than 200 files is stored and resolved whole
    Given a folder of 250 guideline files
    When an admin saves the folder with the reason "A large set"
    Then the writing guidelines are at version 1 with one stored file for each file of the folder
    And exporting the writing guidelines to a new folder gives every file byte for byte as it was in the folder
    And resolving the writing guidelines finds every rule of the folder

  Scenario: A file larger than 256 KiB is stored whole
    Given a folder with one guideline file of 300 KiB
    When an admin saves the folder with the reason "A long file"
    Then the writing guidelines are at version 1 with one stored file for each file of the folder
    And exporting the writing guidelines to a new folder gives every file byte for byte as it was in the folder

  Scenario: Reads page past 500 attachments
    Given a folder of 620 guideline files
    And the database answers each attachment query one page of 100 rows at a time
    When an admin saves the folder with the reason "Many pages"
    Then the writing guidelines are at version 1 with one stored file for each file of the folder
    And exporting the writing guidelines to a new folder gives every file byte for byte as it was in the folder
    And resolving the writing guidelines finds every rule of the folder
