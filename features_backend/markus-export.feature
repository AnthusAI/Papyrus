Feature: Exporting CMS content as a Markus build input
  The exporter writes published items (or drafts, for staging) back into the
  directory layout the Markus static build consumes.

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
