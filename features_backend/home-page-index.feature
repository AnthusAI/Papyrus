@backend @home-page-index
Feature: A site can serve its public blocks from the indexes they show instead of from one file of every Reference
  The home-page snapshot reads the whole corpus into one file (about 8,200 AppSync requests from nothing on Machines on Machines) and every block then picks its few
  cards from the file. A site that sets homePage.references.source to "index" asks the public index for exactly the rows each block shows, in the order it shows
  them, and each row already carries what its card needs, so no decision and no preview is read. The pages are the same pages: the same markup, the same
  Markdown twins, the same order, with an editor's stars first and the unscored last. A change reaches the pages through the stream trigger's coordinates, which say
  which blocks a changed row can touch without reading it; a row that is in no public partition touches nothing and costs nothing. No file of References is
  written, and nothing private is in a page. A site that has not opted in is unchanged. Nothing here touches production: the backend is in memory and every request
  is counted.

  Scenario: The same site rendered from the file and from the index is the same site
    Given a corpus of References with accepted, recommended, starred and video rows
    When the fixture site is rendered from the file and from the public index
    Then every page that places a Reference is identical in both
    And the pages include Markdown twins

  Scenario: A whole site from nothing costs the requests of its blocks and not a read of the corpus
    Given a corpus of References with accepted, recommended, starred and video rows
    When the fixture site is rendered from the public index
    Then fewer than 60 requests were made
    And no decision and no preview was read
    And the star partitions were read once for the whole run and the section labels once
    And no file of References was written

  Scenario: A Reference nobody predicted, or predicted under one half, is never recommended
    Given a corpus of References with accepted, recommended, starred and video rows
    And a pending Reference nobody predicted
    When the fixture site is rendered from the public index
    Then no page shows the unpredicted Reference

  Scenario: A change to a row that is in no public partition costs nothing
    Given a corpus of References with accepted, recommended, starred and video rows
    And the fixture site rendered from the public index
    When a batch arrives that holds no change a block can show
    Then no block was asked and no request was made and no page was rewritten

  Scenario: A Reference accepted after the first render reaches the pages that place accepted References and only those
    Given a corpus of References with accepted, recommended, starred and video rows
    And the fixture site rendered from the public index
    When a new accepted Reference with a high confidence is recorded as a change
    Then the front page shows it
    And the page that places only recommended References is not rewritten

  Scenario: A mass import asks every block once
    Given a corpus of References with accepted, recommended, starred and video rows
    And the fixture site rendered from the public index
    When the trigger reports that a window held more changes than it can list
    Then every block was asked and the run says it was full

  Scenario: A threshold under one half cannot be served from the index
    When the settings name source "index" and a recommended threshold of 0.4
    Then the settings are refused and the message names the threshold

  Scenario: The parity report names a page that differs and the rounding tier
    Given two accepted References whose confidences round to the same percentage
    When the fixture site is rendered from the file and from the public index
    Then the report says the pages differ only inside a rounding tier
    And the check does not fail

  Scenario: A paged list served from the index is cut into the chunks the file makes
    The whole list is read, one request for every hundred rows, so a paged list is the one block whose render still grows with the table; the files of every chunk are
    named from the list, so they are written together or not at all.
    Given a corpus of References with accepted, recommended, starred and video rows
    When the paged fixture site is rendered from the file and from the public index
    Then every page and every chunk file of every paged list is identical in both

  Scenario: A row that cannot be in a paged list asks nothing, and one that can asks the list again
    Given a corpus of References with accepted, recommended, starred and video rows
    And the paged fixture site rendered from the public index
    When a batch arrives that holds no change a block can show
    Then no block was asked and no request was made and no page was rewritten
    When a new recommended Reference is recorded as a change
    Then the paged list shows it
