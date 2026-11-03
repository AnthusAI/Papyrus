Feature: Human ratings shape what the public home page features, and are never published
  An editor's star rating is a stronger signal than the Cyclotron's confidence, so on the automated home pages it overrides it where it exists. One order
  is shared by every selection that ranks References: three, four and five stars first (the most stars first), then the References nobody rated by the
  Cyclotron's confidence, then one and two stars, so a low rating is a real downgrade and sinks a Reference even when the Cyclotron is sure of it. Equal
  References go to the newest arrival, then to the key. The Cyclotron's confidence stays public as it was; the stars never are. The snapshot of References
  is readable by anyone, so the stars are not in it: each record carries a rank, its position in the shared order, which says nothing about how many
  stars anyone gave. A rating that reorders the page changes the file and re-renders the pages that read it, through the same debounce as any other change;
  a rating that moves nothing changes nothing. The "recent" selection with no bucket keeps its newest-accepted order.
  The references include can also sort by time bucket: bucket="day" or bucket="week" puts the newest bucket first and the shared order inside each bucket.
  A bucket is the UTC day, or the UTC week that starts on Monday, of the date the selection already orders by: the accepted time, and for a Reference that
  has none (a recommended one) its arrival. A rating never moves a Reference to another bucket. A bucket other than day or week is a build error naming
  the page. The ledger rules are unchanged.

  Background:
    Given a home-page site whose pages place confident, recommended, recent, weekly, daily and weekly confident grids

  Scenario: Rated References come first, unrated ones follow by confidence, and low ratings come last
    Given editors rated these References: "Accepted one" 5, "Accepted three" 4, "Accepted eight" 2, "Accepted five" 1
    When the home-page-snapshot task runs
    Then the "confident" grid on "by-confidence/index.html" lists "Accepted one", "Accepted three, contact", "Accepted two", "Accepted four", "Accepted seven", "Accepted six", "Accepted eight", "Accepted five"

  Scenario: A rating beats a prediction in both directions
    Given editors rated these References: "Accepted three" 3, "Accepted eight" 2
    When the home-page-snapshot task runs
    Then the "confident" grid on "by-confidence/index.html" lists "Accepted three, contact", "Accepted two", "Accepted four", "Accepted seven", "Accepted five", "Accepted six", "Accepted one", "Accepted eight"

  Scenario: Equal ratings go to the newest arrival
    Given editors rated these References: "Accepted two" 3, "Accepted four" 3, "Accepted seven" 3
    When the home-page-snapshot task runs
    Then the "confident" grid on "by-confidence/index.html" lists "Accepted seven", "Accepted four", "Accepted two", "Accepted eight", "Accepted five", "Accepted six", "Accepted one", "Accepted three, contact"

  Scenario: The recommended selection uses the same order, so a rating can lift or sink a pending Reference
    Given editors rated these References: "Pending mid" 5, "Pending high" 1
    When the home-page-snapshot task runs
    Then the "recommended" grid on "suggested/index.html" lists "Pending mid", "Pending unrecorded confidence", "Pending undecided", "Pending high"

  Scenario: Recent with no bucket keeps its newest-accepted order whatever the ratings
    Given editors rated these References: "Accepted one" 5, "Accepted eight" 1
    When the home-page-snapshot task runs
    Then the "recent" grid on "newest/index.html" lists "Accepted eight", "Accepted seven", "Accepted six", "Accepted five", "Accepted four", "Accepted three, contact", "Accepted two", "Accepted one"

  Scenario: A week bucket puts the newest week first and ranks by rating inside each week
    Given editors rated these References: "Accepted one" 5, "Accepted eight" 1
    When the home-page-snapshot task runs
    Then the "recent" grid on "weekly/index.html" lists "Accepted seven", "Accepted eight", "Accepted one", "Accepted two", "Accepted four", "Accepted five", "Accepted six", "Accepted three, contact"

  Scenario: A day bucket keeps every Reference in its own day, so a rating never moves it to another bucket
    Given editors rated these References: "Accepted one" 5, "Accepted eight" 1
    When the home-page-snapshot task runs
    Then the "recent" grid on "daily/index.html" lists "Accepted eight", "Accepted seven", "Accepted six", "Accepted five", "Accepted four", "Accepted three, contact", "Accepted two", "Accepted one"

  Scenario: A bucket works with the confident selection too
    Given editors rated these References: "Accepted one" 5, "Accepted eight" 1
    When the home-page-snapshot task runs
    Then the "confident" grid on "confident-weekly/index.html" lists "Accepted seven", "Accepted eight", "Accepted one", "Accepted two", "Accepted four", "Accepted five", "Accepted six", "Accepted three, contact"

  Scenario: The stars are never in a published file
    Given editors rated these References: "Accepted one" 5, "Accepted three" 4, "Pending mid" 2
    When the home-page-snapshot task runs
    Then no record in the file has a star field and none names who rated
    And no file the site holds mentions a star rating or who gave one
    And every record has a rank that is a position in the shared order, from 1 to the number of records

  Scenario: A rating that reorders the page changes only the ranks and re-renders the pages that read the file
    Given the home-page-snapshot task has run
    When an editor rates "Accepted one" 5 stars and the home-page-snapshot task runs again
    Then the file is written
    And the only difference in the file is the rank of the References that moved
    And the page "by-confidence/index.html" was re-rendered
    And the page "weekly/index.html" was re-rendered
    And no file the site holds mentions a star rating or who gave one

  Scenario: A rating that moves nothing changes nothing
    Given the home-page-snapshot task has run
    When an editor rates "Accepted eight" 4 stars and the home-page-snapshot task runs again
    Then the file is not written again
    And no page is re-rendered
    And the file keeps "Accepted eight" at rank 1

  Scenario: A bucket that is not day or week is a build error naming the page
    Given a home-page site with a page whose references include has the bucket "month"
    Then the build failed saying "pages/bad.md" and "bucket" and "month"
