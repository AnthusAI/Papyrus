Feature: Human ratings shape what the public home page features, and an accepted Reference shows its stars
  An editor's star rating is a stronger signal than the Cyclotron's confidence, so on the automated home pages it overrides it where it exists. One order
  is shared by every selection that ranks References: three, four and five stars first (the most stars first), then the References nobody rated by the
  Cyclotron's confidence, then one and two stars, so a low rating is a real downgrade and sinks a Reference even when the Cyclotron is sure of it. Equal
  References go to the newest arrival, then to the key. The Cyclotron's confidence stays public as it was. Since 2026-11-04 the stars of an ACCEPTED
  Reference are public too, as the count (1 to 5) on its record in the snapshot; a pending Reference shows its confidence instead, and a Reference nobody
  rated shows no stars. Who rated it and when are never published. Each record also carries a rank, its position in the shared order, which is how the build
  orders the page without reading anyone's rating. A rating that reorders the page, or only changes a count, changes the file and re-renders the pages that
  read it, through the same debounce as any other change. The "recent" selection with no bucket keeps its newest-accepted order.
  The references include can also sort by time bucket: bucket="day" or bucket="week" puts the newest bucket first and the shared order inside each bucket.
  A bucket is a ROLLING window counted back from the UTC day of the render, the same as for Stories (Ryan, 2026-11-05): "week" is the last seven days, the seven
  before that, and so on, and "day" is the last day, the day before, and so on. It is not a calendar day or a Monday week. The date is the one the selection
  already orders by: the accepted time, and for a Reference that has none (a recommended one) its arrival. A rating never moves a Reference to another
  bucket. With time alone a Reference moves to the next older window on the day it turns seven days old (one day for "day"): it then follows every Reference of the
  newer window and is ranked inside the older one. Nothing is dropped. The order depends on the day and never on the time, so a page or a chunk of a paged
  list is written again only when the order it shows changed; a day that moves no Reference across a window rewrites nothing, and nothing is scheduled to
  walk the lists, so a quiet page catches up the next time something re-renders it. A bucket other than day or week is a build error naming the page.
  The ledger rules are unchanged.

  Background:
    Given a home-page site whose pages place confident, recommended, recent, weekly, daily and weekly confident grids

  Scenario: Rated References come first, unrated ones follow by confidence, and low ratings come last
    Given editors rated these References: "Accepted one" 5, "Accepted three" 4, "Accepted eight" 2, "Accepted five" 1
    When the home-page-snapshot task runs
    Then the "confident" grid on "by-confidence/index.html" lists "Accepted one", "Accepted three, contact", "Accepted two", "Accepted four", "Accepted seven", "Accepted six", "Accepted eight", "Accepted five"

  Scenario: A rating beats a prediction in both directions
    Given editors rated these References: "Accepted three" 3, "Accepted eight" 2
    When the home-page-snapshot task runs
    Then the "confident" grid on "by-confidence/index.html" lists "Accepted three, contact", "Accepted two", "Accepted one", "Accepted four", "Accepted seven", "Accepted five", "Accepted six", "Accepted eight"

  Scenario: Equal ratings go to the newest arrival
    Given editors rated these References: "Accepted two" 3, "Accepted four" 3, "Accepted seven" 3
    When the home-page-snapshot task runs
    Then the "confident" grid on "by-confidence/index.html" lists "Accepted seven", "Accepted four", "Accepted two", "Accepted eight", "Accepted one", "Accepted five", "Accepted three, contact", "Accepted six"

  Scenario: The recommended selection uses the same order, so a rating can lift or sink a pending Reference
    Given editors rated these References: "Pending mid" 5, "Pending high" 1
    When the home-page-snapshot task runs
    Then the "recommended" grid on "suggested/index.html" lists "Pending mid", "Pending unrecorded confidence", "Pending high"

  Scenario: Recent with no bucket keeps its newest-accepted order whatever the ratings
    Given editors rated these References: "Accepted one" 5, "Accepted eight" 1
    When the home-page-snapshot task runs
    Then the "recent" grid on "newest/index.html" lists "Accepted eight", "Accepted seven", "Accepted six", "Accepted five", "Accepted four", "Accepted three, contact", "Accepted two", "Accepted one"

  Scenario: A week bucket is the last seven days, then the seven before, and ranks by rating inside each window
    Given editors rated these References: "Accepted one" 5, "Accepted eight" 1
    When the home-page-snapshot task runs
    Then the "recent" grid on "weekly/index.html" lists "Accepted seven", "Accepted six", "Accepted eight", "Accepted one", "Accepted two", "Accepted four", "Accepted five", "Accepted three, contact"

  Scenario: Two days later a Reference has moved to the older window with time alone, and none is dropped
    Given editors rated these References: "Accepted one" 5, "Accepted eight" 1
    And the day of the render is 2026-11-02
    When the home-page-snapshot task runs
    Then the "recent" grid on "weekly/index.html" lists "Accepted eight", "Accepted one", "Accepted two", "Accepted four", "Accepted seven", "Accepted five", "Accepted three, contact", "Accepted six"

  Scenario: A day bucket keeps every Reference in its own day, so a rating never moves it to another bucket
    Given editors rated these References: "Accepted one" 5, "Accepted eight" 1
    When the home-page-snapshot task runs
    Then the "recent" grid on "daily/index.html" lists "Accepted eight", "Accepted seven", "Accepted six", "Accepted five", "Accepted four", "Accepted three, contact", "Accepted two", "Accepted one"

  Scenario: A bucket works with the confident selection too
    Given editors rated these References: "Accepted one" 5, "Accepted eight" 1
    When the home-page-snapshot task runs
    Then the "confident" grid on "confident-weekly/index.html" lists "Accepted seven", "Accepted six", "Accepted eight", "Accepted one", "Accepted two", "Accepted four", "Accepted five", "Accepted three, contact"

  Scenario: An accepted Reference carries its stars, a pending one does not, and nobody's name or time is published
    Given editors rated these References: "Accepted one" 5, "Accepted three" 4, "Pending mid" 2
    When the home-page-snapshot task runs
    Then the record titled "Accepted one" has 5 stars
    And the record titled "Accepted three, contact" has 4 stars
    And the record titled "Accepted two" has no stars
    And the record titled "Pending mid" has no stars
    And no record in the file names who rated or when
    And no file the site holds mentions who rated or when
    And every record has a rank that is a position in the shared order, from 1 to the number of records

  Scenario: A rating that reorders the page changes the ranks and that record's stars, and re-renders the pages that read the file
    Given the home-page-snapshot task has run
    When an editor rates "Accepted one" 5 stars and the home-page-snapshot task runs again
    Then the file is written
    And the only differences in the file are the ranks of the References that moved and the stars of "Accepted one"
    And the page "by-confidence/index.html" was re-rendered
    And the page "weekly/index.html" was re-rendered
    And no file the site holds mentions who rated or when

  Scenario: A rating that moves nothing still reaches the page, because the page prints the count
    Given the home-page-snapshot task has run
    When an editor rates "Accepted eight" 4 stars and the home-page-snapshot task runs again
    Then the file is written
    And the only differences in the file are the ranks of the References that moved and the stars of "Accepted eight"
    And the file keeps "Accepted eight" at rank 1
    And the record titled "Accepted eight" has 4 stars

  Scenario: Clearing a rating removes the stars from the record
    Given editors rated these References: "Accepted one" 5
    And the home-page-snapshot task has run
    When an editor clears the rating of "Accepted one" and the home-page-snapshot task runs again
    Then the record titled "Accepted one" has no stars

  Scenario: A bucket that is not day or week is a build error naming the page
    Given a home-page site with a page whose references include has the bucket "month"
    Then the build failed saying "pages/bad.md" and "bucket" and "month"
