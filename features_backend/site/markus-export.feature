Feature: Stories are exported as the input of the static site build
  The exporter writes Stories back into the directory layout the Markus static build reads: published Stories only for the live
  site, drafts as well for staging. Old addresses of a Story become redirect rules, and an export that would write nothing fails
  instead of producing an empty site.

  Scenario: Exporting published content writes only published items
    Given a CMS with a published article and a draft article
    When I export the published content
    Then the export contains "articles/live.md"
    And the export does not contain "articles/wip.md"

  Scenario: Exporting drafts includes unpublished items
    Given a CMS with a published article and a draft article
    When I export the drafts
    Then the export contains "articles/live.md"
    And the export contains "articles/wip.md"

  Scenario: An empty export fails
    Given an empty CMS
    When I export the published content
    Then the export fails with "no items"

  Scenario: Aliases become redirect rules
    Given a CMS with a published article aliased from "/blog/live-old"
    When I export the published content
    Then the redirects map "/blog/live-old" to "/articles/live.html"
