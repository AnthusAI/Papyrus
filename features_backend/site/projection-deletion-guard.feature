Feature: Projection refuses deletions that look like a wrong site configuration
  A whole-site projection or a reconcile reads the site's configuration to
  decide which pages each published item has. When that configuration is wrong
  or out of date, for example a checkout of the site that is many commits
  behind, a published item can end up with no pages, and everything the store
  remembers for it would be deleted. The operator commands therefore refuse,
  before writing anything, to delete the pages of an item that stays published
  or to delete more than a tenth of the stored pages. Passing
  --allow-deletions turns the guard off. The live publish functions keep no
  guard. An ordinary edit, such as unpublishing one article, is never refused.

  Background:
    Given a guarded site of three published articles that has been projected

  Scenario: Re-projecting with a site configuration that no longer places a published section refuses and deletes nothing
    When the site configuration stops placing the article "seed-1" and the whole site is projected
    Then the projection is refused
    And the refusal names the page "articles/seed-1.html" and the item "item-1"
    And the refusal says to check that --static-dir is a current checkout or to pass --allow-deletions
    And the site store is exactly as it was

  Scenario: --allow-deletions lets the deletions through
    When the site configuration stops placing the article "seed-1" and the whole site is projected with deletions allowed
    Then the projection is not refused
    And the page "articles/seed-1.html" no longer exists

  Scenario: A projection that would delete a large share of the stored pages refuses even when every item keeps a page
    Given the site remembers thirty more pages for the article "seed-0"
    When the whole site is projected
    Then the projection is refused
    And the refusal counts 30 pages under "articles/"
    And the site store is exactly as it was

  Scenario: A renamed article still re-projects
    When the article "seed-1" is renamed to "renamed-one" and the whole site is projected
    Then the projection is not refused
    And the page "articles/seed-1.html" no longer exists
    And the page "articles/renamed-one.html" exists

  Scenario: A reconcile that would delete a dropped item's pages refuses
    When the site configuration stops placing the article "seed-1" and the site is reconciled
    Then the projection is refused
    And the refusal names the page "articles/seed-1.html" and the item "item-1"
    And the site store is exactly as it was

  Scenario: Unpublishing one item still reconciles
    When the article "seed-2" is unpublished and the site is reconciled
    Then the projection is not refused
    And the page "articles/seed-2.html" no longer exists
    And the page "articles/seed-1.html" exists
