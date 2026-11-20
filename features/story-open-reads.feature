@brand-agnostic
Feature: Opening a story reads only that story's records
  Opening a story on the board, or its full page, used to read the whole relation table twice: once so the editor could say "version 2 of
  5", and again for the References tab, each time paging through every relation in the site, 200 at a time, to find the few that belong to
  this story. Now the editor asks for the newest version with one indexed read of one row, and the References come from the index keyed by
  the story (the same read `papyrus stories references` makes). These scenarios use a fake backend that records every query; they never
  touch production.

  Scenario: The editor learns the newest version with one small read
    Given a story with three saved versions
    When an editor opens its oldest version
    Then the console asks for the newest version with one indexed read of one row
    And it does not load the story's reporting trail to find it

  Scenario: The References tab reads the story's own relations
    Given a story with one cited Reference in a site with thousands of other relations
    When the References tab loads
    Then it shows the cited Reference with its role
    And it read the relations keyed by the story and never paged through the relation table
