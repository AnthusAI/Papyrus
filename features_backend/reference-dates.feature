@backend @reference-dates
Feature: Every Reference carries the date its source was published, when the source says
  A Reference has two dates. The first is when it was added to the site, which Papyrus always knows. The
  second is when the source itself was published, which Papyrus only knows if someone or something said
  so. When curation reads an HTML page it looks for the date the page declares for itself: the Open
  Graph article published time, the JSON-LD date published (also inside a graph), or a time element. A
  date found that way is stored as the Reference's publication date, together with where it came from
  and how precise it is. A date that a monitor already supplied is kept. A page that declares no date
  leaves the publication date empty, and the date the Reference was added is never copied into it.

  Background:
    Given a site with a pending Reference whose source page declares its date in no way yet

  Scenario: A page that declares an Open Graph published time gives its publication date
    Given the page declares the Open Graph article published time "2026-10-28T09:30:00Z"
    When curation reads the page
    Then the Reference's publication date is "2026-10-28"
    And the publication date was resolved from "og:article:published_time" with "day" precision

  Scenario: A page that declares a JSON-LD date published gives its publication date
    Given the page declares the JSON-LD date published "2026-09-15"
    When curation reads the page
    Then the Reference's publication date is "2026-09-15"
    And the publication date was resolved from "json-ld" with "day" precision

  Scenario: A JSON-LD date published inside a graph is found
    Given the page declares the date published "2026-08-02T04:00:00-05:00" inside a JSON-LD graph
    When curation reads the page
    Then the Reference's publication date is "2026-08-02"
    And the publication date was resolved from "json-ld" with "day" precision

  Scenario: A time element is the last place Papyrus looks
    Given the page shows a time element with the datetime "2026-07-04"
    When curation reads the page
    Then the Reference's publication date is "2026-07-04"
    And the publication date was resolved from "time-element" with "day" precision

  Scenario: A date that only names a month is stored with month precision
    Given the page declares the Open Graph article published time "2026-06"
    When curation reads the page
    Then the Reference's publication date is "2026-06-01"
    And the publication date was resolved from "og:article:published_time" with "month" precision

  Scenario: A page that declares no date leaves the publication date empty
    When curation reads the page
    Then the Reference has no publication date
    And the Reference records no publication date resolution
    And the Reference's added date is unchanged

  Scenario: A date a monitor supplied is kept over the date the page declares
    Given the Reference already has the publication date "2026-10-01" from a monitor
    And the page declares the Open Graph article published time "2026-10-28T09:30:00Z"
    When curation reads the page
    Then the Reference's publication date is "2026-10-01"
    And the publication date was resolved from "monitor" with "day" precision

  Scenario: A pack states the basis of its dates and never writes a publication date for an unknown one
    Given References accepted in a burst, one with no publication date
    When the context packs are built from them
    Then the acceptance pack states that its dates are ingestion dates
    And the Reference with no publication date shows no publication date and is ordered by its added date

  Scenario: Inside a pack References are ordered by their publication date
    Given References accepted in a burst, with publication dates far apart
    When the context packs are built from them
    Then the Reference published most recently comes first in the acceptance pack

  Scenario: The concept trend series counts by publication date
    Given a concept linked to items published in three different weeks
    When the concept snapshot files are built
    Then each item is counted in the week it was published
    And the concept series states that its dates are publication dates

  Scenario: An old source that people suddenly attend to yields a resurfaced pack
    Given a site where sources usually reach it days after publication
    And a source published long before it reached the site that people accepted and discussed today
    When the context packs are built from them
    Then a resurfaced pack exists for that source
    And the pack states that its dates are publication dates
    And the pack says the accept and the Message that pointed attention at it

  Scenario: An old source that nobody attends to yields no resurfaced pack
    Given a site where sources usually reach it days after publication
    And a source published long before it reached the site that nobody has attended to for months
    When the context packs are built from them
    Then no resurfaced pack exists

  Scenario: The backfill resolves dates for existing References without running the rest of curation
    Given Reference "dated-a" has a page that declares the Open Graph article published time "2026-10-28T09:30:00Z"
    And Reference "dated-b" already has the publication date "2026-10-01" from a monitor
    And Reference "dated-c" has a page that cannot be fetched
    And Reference "dated-d" already has a recorded publication date resolution
    When the publication date backfill runs
    Then Reference "dated-a" has the publication date "2026-10-28" resolved from "og:article:published_time"
    And Reference "dated-b" records its publication date as resolved from "monitor"
    And Reference "dated-c" is unchanged and counted as a fetch failure
    And Reference "dated-d" is skipped
    And no summary was written and no curation card exists for any of them

  Scenario: A dry run of the backfill writes nothing
    Given Reference "dated-a" has a page that declares the Open Graph article published time "2026-10-28T09:30:00Z"
    When the publication date backfill runs as a dry run
    Then the dry run lists Reference "dated-a" with the date "2026-10-28" from "og:article:published_time"
    And the dry run wrote nothing
