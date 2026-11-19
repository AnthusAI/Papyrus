@backend @three-star-floor
Feature: Three stars is the minimum for anything on a public page or in a notification
  Ryan, 2026-11-12: "Three stars is our minimum standard for including anything on any public page or notification. References, Posts, Articles, anything."
  An item may be public only when its effective human rating (item_stars.effective_rating) is at or above the site's floor. Unrated is no rating and never
  qualifies, and a Cyclotron prediction is a model's guess, not a rating, so it never qualifies however sure it is. An editor accepting a Reference or
  publishing a Story without stars does not qualify it either: the page of such a Story stays served at its address and nothing is unpublished, it is just
  not listed, fed, put in the sitemap, searched or mailed until someone rates it.

  The floor is a site setting, quality.floorStars in projection.json, a whole number from 1 to 5 that is 3 when the quality block is there without a number.
  A site may raise it and can never lower it below 1, because unrated can never be included. A site with no quality block has no floor, and nothing changes
  for it until it adds one: the floor is turned on per site, one site under test first.

  One rule serves every surface. The Story side drops a Story under the floor where the projector builds the entries that listings, tag and section pages,
  the home page, the feeds, the sitemap, llms-full and the public data files all read. The Reference side drops it where the home page snapshot decides what is
  public, so the Findings, Videos and every other Reference block see only items that passed. A list with too few items shows fewer and is never filled with
  unrated or predicted ones; a list with nothing that qualifies renders nothing at all. A rating change rebuilds the pages that list the item through the
  existing rating path, with no new scan. Stars stay private: only items that passed appear, never a count.

  The newsletter roundup takes only the Stories at the floor and shows the others, in a section the editor deletes before sending, as left out for not
  reaching the floor. The announcement path already refuses anything under three stars and fires once ever per Story when its rating reaches the bar.

  Scenario: Rated Stories qualify on every surface
    Given a site with the quality floor on and a Story rated four stars and a Story rated three stars
    Then both Stories are on the home page, the listing page, the feed, the sitemap and the public data

  Scenario: An unrated Story is served by its address and listed nowhere
    Given a site with the quality floor on and a Story nobody rated
    Then the Story is not on the home page, the listing page, the feed, the sitemap or the public data
    And the page of the Story is still served

  Scenario: One and two stars do not qualify
    Given a site with the quality floor on and Stories rated one, two and three stars
    Then only the three-star Story is listed anywhere

  Scenario: A site with no quality setting changes nothing
    Given a site with no quality setting and Stories rated and unrated
    Then every Story is listed everywhere, rated or not

  Scenario: A site raises the floor
    Given a site whose quality floor is four stars and Stories rated three and four stars
    Then only the four-star Story is listed anywhere

  Scenario: Too few items shows fewer, and nothing qualifying shows nothing
    Given a site with the quality floor on and no Story rated
    Then the listing page shows no Story and the feed and the sitemap list none

  Scenario: Rated down and rated up
    Given a site with the quality floor on and a Story rated four stars
    When an editor rates it two stars
    Then the listings, the feed and the sitemap no longer have it
    When an editor rates it three stars
    Then the listings, the feed and the sitemap have it again

  Scenario: A prediction is not a rating, and accepting without stars does not qualify
    Given a site with the quality floor on and a pending Reference the Cyclotron is 95 percent sure about and an accepted Reference nobody rated
    Then neither Reference is in the public snapshot and no recommended Reference is

  Scenario: Rated References at the floor are public
    Given a site with the quality floor on and accepted References rated one, two, three and five stars
    Then the public snapshot holds the three-star and the five-star Reference only

  Scenario: A site raises the floor for References
    Given a site whose quality floor is four stars and accepted References rated three and four stars
    Then the public snapshot holds the four-star Reference only

  Scenario: The roundup keeps the Stories at the floor and shows the rest as left out
    Given a site with the quality floor on and a week of five published Stories, two rated three stars or more
    When the roundup draft is assembled
    Then the draft names the two rated Stories as the issue
    And the draft shows the other three under a Left out heading as not reaching the floor

  Scenario: A week with nothing at the floor makes no roundup
    Given a site with the quality floor on and a week of published Stories nobody rated
    When the roundup is assembled on its schedule
    Then no draft is made

  Scenario: Every surface follows when ratings become an aggregate of votes
    Given a quality floor of three stars
    Then the floor reads the rating only through the effective rating function the quality code already uses
