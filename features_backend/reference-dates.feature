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
