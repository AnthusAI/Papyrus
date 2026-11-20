@backend @home-page-references-min-stars
Feature: A references include can leave out References an editor rated below a minimum, before the count, the ledger and paging
  A site can keep the References an editor rated two stars or lower out of a list (a videos page, a section's videos, a Worth Watching panel) with
  minStars="3". The snapshot already carries the stars of an accepted Reference, so nothing is read from the backend. Like section and notMedium it narrows
  the candidates before the count, the page ledger and the paging, so an excluded Reference takes no slot on the page and no place on a later page, no chunk
  file of a paged list is empty, a list with fewer eligible References than its count stays shorter, and the Markdown twin lists what the page lists. A
  Reference nobody rated passes, and a Reference rated at the minimum or above passes in the order it already had. The filter changes only the list that
  asks for it: the Reference stays accepted in the snapshot, and a list without minStars still shows it.

  Scenario: Low-rated videos are absent from the page and from every page of a paged list
    Given a snapshot of 30 accepted videos in which the newest 8 are rated 1 or 2, 6 are rated 3 to 5 and the rest are unrated
    And a page with a paged videos include with minStars "3"
    When the minimum stars site is projected
    Then no video rated 1 or 2 is on the page or in any data file of its lists
    And the paged list holds the 22 videos not rated 1 or 2, each once, and no data file of it is empty

  Scenario: Low-rated videos do not take a slot of a counted list
    Given a snapshot of 30 accepted videos in which the newest 8 are rated 1 or 2, 6 are rated 3 to 5 and the rest are unrated
    And a page with a counted videos include with minStars "3" and a count of 6
    When the minimum stars site is projected
    Then the page shows 6 videos and none of them is rated 1 or 2

  Scenario: A list with fewer eligible videos than its count stays shorter
    Given a snapshot of 10 accepted videos in which 7 are rated 1 or 2 and 3 are rated 4
    And a page with a counted videos include with minStars "3" and a count of 6
    When the minimum stars site is projected
    Then the page shows 3 videos and none of them is rated 1 or 2

  Scenario: A rating of three or higher stays eligible and unrated videos are unchanged
    Given a snapshot of 30 accepted videos in which the newest 8 are rated 1 or 2, 6 are rated 3 to 5 and the rest are unrated
    And a page with a counted videos include with minStars "3" and a count of 50
    When the minimum stars site is projected
    Then the page shows the 22 videos not rated 1 or 2 in the order a page without minStars gives them

  Scenario: The Markdown twin lists what the page lists
    Given a snapshot of 30 accepted videos in which the newest 8 are rated 1 or 2, 6 are rated 3 to 5 and the rest are unrated
    And a page with a counted videos include with minStars "3" and a count of 50
    When the minimum stars site is projected
    Then the Markdown twin of the page lists the same References as the page

  Scenario: A list that does not ask for minStars still shows a low-rated video, which is still accepted
    Given a snapshot of 30 accepted videos in which the newest 8 are rated 1 or 2, 6 are rated 3 to 5 and the rest are unrated
    And a page with a counted videos include with no minStars and a count of 50
    When the minimum stars site is projected
    Then the page shows all 30 videos

  Scenario: minStars must be a rating from 2 to 5
    Given a snapshot of 30 accepted videos in which the newest 8 are rated 1 or 2, 6 are rated 3 to 5 and the rest are unrated
    And a page with a counted videos include with minStars "9" and a count of 6
    Then projecting the minimum stars site stops and the error names the page and the allowed ratings
