Feature: Editors refresh pages at the edge on demand
  The site's cache keeps a page for an hour by default, and that stays. When an
  editor must see an edit now, four explicit operations exist, one definition
  behind the command line and the MCP tools. Refreshing a page, a Story or the
  index pages purges exact paths at the edge and nothing else; re-rendering
  rebuilds pages from the hooks the site has deployed and then purges what it
  wrote. A page is cached under more than one address (a directory and its
  index.html), so every address of every page is purged, with the page's
  Markdown twin. The whole site is never purged. Each result says what was
  written (re-render only) and what was invalidated as separate outcomes, with
  the number of paths, what they cost at most, and the CloudFront invalidation
  id and status. A dry run prints the paths and invalidates nothing.

  Background:
    Given a site with four articles in two pages of the articles section and one video

  Scenario: Refreshing a page purges both URL forms and the Markdown twin
    When the editor refreshes the page "/articles/a1/"
    Then the refresh succeeded
    And the edge was asked to invalidate exactly "/articles/a1/", "/articles/a1/index.html" and "/articles/a1/index.md"
    And the result names the CloudFront invalidation id and its status

  Scenario: Naming either form of a page refreshes the same pages
    When the editor refreshes the page "/articles/a1/index.html"
    Then the edge was asked to invalidate exactly "/articles/a1/", "/articles/a1/index.html" and "/articles/a1/index.md"

  Scenario: A dry run prints the paths and invalidates nothing
    When the editor refreshes the page "/articles/a1/" as a dry run
    Then the refresh succeeded
    And the result lists "/articles/a1/index.html" among the paths
    And the edge was not asked to invalidate anything

  Scenario: Refreshing a Story purges its page and every index page that lists it
    When the editor refreshes the Story "file:articles/a1.md"
    Then the refresh succeeded
    And the paths invalidated include "/articles/a1/", "/articles/a1/index.html" and "/articles/a1/index.md"
    And the paths invalidated include the home page, the articles list page and their Markdown twins in both URL forms
    And the paths invalidated do not include "/articles/page/2/" or anything under "/videos/"

  Scenario: An older Story also purges the page of the paging it is on
    When the editor refreshes the Story "file:articles/a4.md"
    Then the paths invalidated include "/articles/page/2/" and "/articles/page/2/index.html"

  Scenario: Refreshing the index pages purges the home page, every list page and every section page
    When the editor refreshes the index pages
    Then the refresh succeeded
    And the paths invalidated include "/", "/index.html", "/articles/", "/articles/page/2/", "/videos/" and "/videos/index.html"
    And the paths invalidated name no Story page
    And no path invalidated is a wildcard

  Scenario: A large refresh stays exact paths and never becomes a whole-site purge
    When the editor refreshes 1200 pages
    Then no path invalidated is a wildcard
    And the edge received more than one request of at most 3000 paths each

  Scenario: The result says how many paths and what they cost at most
    When the editor refreshes the index pages
    Then the result says how many paths were invalidated
    And the result says the first 1000 paths a month are free and each one after costs 0.005 USD

  Scenario: A wildcard is refused
    When the editor refreshes the page "/articles/*"
    Then the request is refused as invalid input
    And the edge was not asked to invalidate anything

  Scenario: Refreshing a Story that is not published is refused
    When the editor refreshes the Story "no-such-story"
    Then the request is refused as not found
    And the edge was not asked to invalidate anything

  Scenario: Re-rendering reports what it wrote apart from what it invalidated
    When the editor re-renders the index pages
    Then the re-render wrote the home page and the articles list page
    And the paths invalidated include "/articles/" and "/articles/index.html"
    And the re-render outcome is ok and the invalidation outcome is ok

  Scenario: Re-rendering one Story rewrites that Story's pages
    When the editor re-renders the Story "file:articles/a2.md"
    Then the re-render wrote "articles/a2/index.html"
    And the paths invalidated include "/articles/a2/" and "/articles/a2/index.html"

  Scenario: A re-render dry run writes nothing and invalidates nothing
    When the editor re-renders the whole site as a dry run
    Then the result lists the pages it would write
    And nothing was written to the site
    And the edge was not asked to invalidate anything

  Scenario: A failed invalidation after a good re-render is reported on its own
    Given the edge rejects invalidations
    When the editor re-renders the index pages
    Then the re-render outcome is ok and the invalidation outcome is failed with a reason
    And the refresh did not succeed

  Scenario: The command exits non-zero when the invalidation failed
    Given the edge rejects invalidations
    When an operator runs the page refresh command "refresh --path /articles/a1/"
    Then the page refresh command exits with status 1
    And the page refresh command output says the invalidation FAILED

  Scenario: The command prints the invalidation id, the count and the cost
    When an operator runs the page refresh command "refresh --story file:articles/a1.md"
    Then the page refresh command exits with status 0
    And the page refresh command output lists the paths, the cost and the CloudFront invalidation id with its status

  Scenario: The command repeats --path for several pages and --json prints the same result
    When an operator runs the page refresh command "refresh --path /articles/a1/ --path /videos/v1/ --json"
    Then the page refresh command exits with status 0
    And the page refresh command printed JSON for the operation "site_refresh_pages" with 6 paths

  Scenario: The command's dry run invalidates nothing
    When an operator runs the page refresh command "refresh --indexes --dry-run"
    Then the page refresh command exits with status 0
    And the edge was not asked to invalidate anything

  Scenario: The command wants exactly one thing to refresh
    When an operator runs the page refresh command "refresh --indexes --story file:articles/a1.md"
    Then the page refresh command is refused with "Pass exactly one of"

  Scenario: The MCP tools are the same operations with the same result
    When an agent calls the tool "site_refresh_story" with the Story "file:articles/a1.md"
    Then the tool result is the same JSON the page refresh command prints for that Story
    And the tool list is site_refresh_pages, site_refresh_story, site_refresh_indexes and site_rerender_pages
