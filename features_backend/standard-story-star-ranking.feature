Feature: Published Stories rank by recency bucket and then by the editors' private stars
  An editor can rate a Story from one to five stars (setItemStars). Those stars are private editorial judgement, and now they also shape what a reader
  sees first: Ryan's words are "we're going to rank posts by quality also just like every story, so the posts page should be just like the others:
  most-recent time-bucketed posts from the last week, ranked by star rating."

  The rule is the one References already follow (home-page-human-ratings.feature), applied to Stories wherever the site lists them: listing includes
  (::include{kind="listing"}), the featured slot of a listing page, the home page's list, a section's listing page (/articles/), a collection page
  (/posts/) and a tag page. Newest bucket first; inside a bucket five, four and three stars first, then Stories nobody rated, then two and one stars; equal
  Stories keep their newest-first order. A bucket is a calendar week starting on Monday, in UTC, unless the site (listings.bucket) or the include
  (bucket="day|week|none") says otherwise; "none" is the plain newest-first list.

  Nothing disappears. A Story from an earlier bucket follows every Story of the newer buckets, ranked inside its own bucket, so an old five-star Story never
  rises above a newer week. A Story is rated on its working Item version and the rating is read at projection time from a private store in the
  projection lock table (never beside the pages); the feeds, the sitemap and llms.txt keep date order, and no star value, score or hint is written to any
  public file. A site where nothing is rated lists exactly as it did before, byte for byte.

  When an editor changes a rating, the site records it and re-renders only the listing pages whose order the rating changed: no Story page, no page whose
  order did not move, and no scan of the Items beyond the one that changed.

  Background:
    Given a site of seven Stories this week, one five-star candidate on Monday of that week, and two Stories from the week before

  Scenario: Nothing is rated, so every listing is exactly what it was
    When the site is projected again
    Then every page is byte for byte what it was
    And the "latest" listing is eight, seven, six, five, four, three, star, old-a, old-b

  Scenario: A five-star Story stays the hero above six newer, lower-rated Stories of its week
    Given the editors rated "star" 5 stars and "eight", "seven", "six", "five", "four" and "three" 2 stars
    When the site is projected again
    Then the "hero" listing is star
    And the featured slot of the "posts" listing page is star

  Scenario: Inside a bucket Stories rank by stars, then unrated, then the low ratings
    Given the editors rated "seven" 5, "six" 4, "five" 3, "four" 2 and "three" 1 stars
    When the site is projected again
    Then the "latest" listing is seven, six, five, eight, star, four, three, old-a, old-b

  Scenario: Older Stories are not dropped, they follow in earlier buckets
    Given the editors rated "old-b" 5 stars and "eight" 1 star
    When the site is projected again
    Then the "latest" listing is seven, six, five, four, three, star, eight, old-b, old-a
    And every Story is still on the "posts" listing page

  Scenario: Section pages, collection pages and the home page rank the same way
    Given the editors rated "three" 5 stars
    When the site is projected again
    Then the first Story of the "posts" listing page is three
    And the first Story of the "everything" listing page is three
    And the first Story on the home page is three
    And the feed lists "eight" before "three"

  Scenario: A day bucket and no bucket
    Given the editors rated "three" 5 stars
    When the site is projected again
    Then the "days" listing is eight, seven, six, five, four, three, star, old-a, old-b
    And the "plain" listing is eight, seven, six, five, four, three, star, old-a, old-b
    And the "latest" listing starts with three

  Scenario: A site can make none its default bucket
    Given a site whose listings.bucket is none and the editors rated "three" 5 stars
    When the site is projected again
    Then the "latest" listing is eight, seven, six, five, four, three, star, old-a, old-b

  Scenario: A bucket that is not day, week or none is a build error naming the setting or the page
    Then a listings.bucket of "month" is refused saying "listings.bucket must be one of day, week, none"
    And an include with bucket "month" is refused saying "bucket must be one of day, week, none"

  Scenario: No star value, score or hint is in any public file
    Given the editors rated "three" 5 stars and "six" 1 star
    When the site is projected again
    Then no file the site holds mentions a star rating, who gave one, or the private rating store

  Scenario: A rating that moves a Story re-renders only the listings that show the move
    Given the site has been projected
    When an editor rates "three" 5 stars and the story-stars task runs
    Then the task records the rating and rewrites the pages "index.html", "latest/index.html", "hero/index.html", "posts/index.html" and "everything/index.html"
    And the pages "days/index.html" and "plain/index.html" were not rewritten
    And no Story page was rendered again

  Scenario: The same rating twice, or a rating that moves nothing, rewrites nothing
    Given the site has been projected
    When an editor rates "three" 5 stars and the story-stars task runs
    And the story-stars task runs again for "three"
    Then the second run reports that nothing was recorded and no page was rewritten

  Scenario: Clearing a rating puts the Story back in date order
    Given the editors rated "three" 5 stars
    And the site is projected again
    When an editor clears the rating of "three" and the story-stars task runs
    Then the "latest" listing is eight, seven, six, five, four, three, star, old-a, old-b

  Scenario: A Story nobody has published yet is recorded and renders nothing
    When an editor rates an unpublished Story 4 stars and the story-stars task runs
    Then the task records the rating and rewrites no page

  Scenario: A Story rated before the site had ever heard of a rating is ranked from its first projection
    The private rating store starts empty. A Story it has not seen is read once from its Item rows and remembered, so a rating given before the Story was
    published, or before this feature existed, counts without anyone rating it again.
    Given the editors rated "three" 5 stars
    When the site is projected again
    Then the "latest" listing starts with three
    And the store holds the rating once and a second projection reads it without reading the Items again
