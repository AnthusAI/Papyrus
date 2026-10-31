Feature: The home-page snapshot publishes the accepted and recommended References as public JSON
  A Papyrus site can show part of its newsroom's curation to visitors. The first step is a public data file,
  _data/home-page/references.json, that holds the site's accepted References and the pending ones that the
  Cyclotron expects an editor to accept. A projection task writes it under the projection lease, only when its content
  changed (the freshness stamp alone is not a change), and then re-renders only the pages that read it.
  papyrus home-page snapshot runs the same code from a workstation, against a local directory or a site bucket.

  The file holds an explicit allowlist of fields and nothing else. Anything that identifies a person (who decided, who
  relayed, the editor's private note, intake provenance), the captured text of the source and the model's internal keys
  stay out. Each Reference is named by a short hash of its lineage, so no id appears.

  Scenario: A site without a homePage setting writes no home-page files and the projector ignores the task
    Given a site whose projection.json has no homePage setting
    When the home-page-snapshot task runs
    Then the task reports that the site has no homePage setting
    And the store holds no key under _data/home-page

  Scenario: Accepted current References are exported newest-accepted first with every public field and no excluded field
    Given a site whose projection.json has a homePage setting for a corpus of accepted, pending, rejected and archived References
    When the home-page-snapshot task runs
    Then the accepted titles in the file, in order, are "Accepted eight", "Accepted seven", "Accepted six", "Accepted five", "Accepted four", "Accepted three, contact", "Accepted two", "Accepted one"
    And every record has exactly the public fields in the allowlist order
    And no record has an excluded field
    And the file mentions none of the excluded values the fixture holds
    And the file does not list "Superseded old version"

  Scenario: Pending References at or above the recommended threshold are exported as recommended; rejected, archived and superseded ones never are
    Given a site whose projection.json has a homePage setting for a corpus of accepted, pending, rejected and archived References
    When the home-page-snapshot task runs
    Then the recommended titles in the file are "Pending high", "Pending mid", "Pending unrecorded confidence", "Pending undecided"
    And every recommended record has no acceptedAt
    And the file does not list "Pending low", "Pending predicted reject", "Rejected", "Archived", "Superseded old version"

  Scenario: The live Cyclotron decision sets confidence the way the newsroom console computes it
    A decision for the other label counts for the opposite (0.9 sure of "exclude" is 0.1 to accept). A label other than
    include is positive only when the decision names it. A decision with no recorded confidence is a mild lean (0.6).
    No decision at all is 0.5.
    Given a site whose projection.json has a homePage setting for a corpus of accepted, pending, rejected and archived References
    When the home-page-snapshot task runs
    Then the record titled "Accepted two" has confidence 0.93
    And the record titled "Accepted three, contact" has confidence 0.1
    And the record titled "Accepted four" has confidence 0.8
    And the record titled "Accepted five" has confidence 0.6
    And the record titled "Accepted one" has confidence 0.5

  Scenario: A preview attachment supplies image and summary; a Reference without one has neither field
    Given a site whose projection.json has a homePage setting for a corpus of accepted, pending, rejected and archived References
    When the home-page-snapshot task runs
    Then the record titled "Accepted two" has an image, a summary and a site name
    And the record titled "Accepted four" has no image, no summary and no site name
    And the summary of "Accepted one" is at most 240 characters and ends on a sentence boundary

  Scenario: The public files hold no email, person id, Cognito sub or UUID
    The fixture's titles and addresses carry an email on purpose; the export scrubs them, and the same scanner that
    checks the reader files finds nothing, with no reader id allowed.
    Given a site whose projection.json has a homePage setting for a corpus of accepted, pending, rejected and archived References
    When the home-page-snapshot task runs
    Then the identity scanner finds nothing in the file

  Scenario: An unchanged snapshot is not rewritten and no page is re-rendered
    Given a site whose projection.json has a homePage setting for a corpus of accepted, pending, rejected and archived References
    When the home-page-snapshot task runs
    And the home-page-snapshot task runs again with no change in the References
    Then the file is not written again
    And no page is re-rendered

  Scenario: A changed snapshot rewrites only the pages that read it
    Pages that place a references include read the file; a page without one is not rewritten.
    Given a site with pages that place a references include and a homePage setting for a corpus of accepted, pending, rejected and archived References
    When the home-page-snapshot task runs
    And a Reference is accepted and the home-page-snapshot task runs again
    Then the file is written
    And only pages that read the file are re-rendered
    And the page "front/index.html" was re-rendered
    And the page "quiet/index.html" was not re-rendered

  Scenario: Reconcile leaves _data/home-page files alone
    Given a site whose projection.json has a homePage setting for a corpus of accepted, pending, rejected and archived References
    When the home-page-snapshot task runs
    And the site is reconciled
    Then the file is still in the store

  Scenario: The snapshot honours urls.basePath
    Given a site whose projection.json has a homePage setting and the base path "updates"
    When the home-page-snapshot task runs
    Then the file is stored at "updates/_data/home-page/references.json"

  Scenario: papyrus home-page snapshot --dry-run writes nothing and prints the report
    When papyrus home-page snapshot --dry-run runs against an empty output directory
    Then the output directory is still empty
    And the CLI printed the number of References and the size of the file
