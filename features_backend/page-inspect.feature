Feature: An editor or agent can find out exactly what is wrong with a page
  Inspecting a Story's page reads each stage of the path from an edit to a
  reader and says which stage is behind: the record (every version, the
  current one and the published pointer), the page stored in the site bucket
  (when it was written and which version it was rendered from, by the
  source-version marker and the stored version) and the public edge (status,
  age, last-modified, etag, cache hit and the version it serves). One verdict
  names the stage, with the exact command to repair it. Inspecting reads and
  changes nothing; asked to fix, it makes the smallest repair, looks again and
  says what it found.

  Scenario: The edge serves a copy cached before the page was stored
    Given the record is published at version 7 and the stored page was rendered from version 7
    And the edge serves a copy last modified before the page was stored
    When the editor inspects the Story
    Then the inspect verdict is "edge-stale"
    And the inspect verdict names the stored version 7 and the copy's age of 3169 s
    And the inspect evidence lists all 7 record versions and the published pointer at version 7
    And the inspect evidence shows the edge status, age, etag, cache hit and s-maxage

  Scenario: The edge serves an older version by its marker
    Given the record is published at version 7 and the stored page was rendered from version 7
    And the edge serves version 6
    When the editor inspects the page "/articles/containment/"
    Then the inspect verdict is "edge-stale"
    And the inspect verdict says the edge serves version 6

  Scenario: A published page that was never projected again
    Given the record is published at version 7 and the stored page was rendered from version 6
    When the editor inspects the Story
    Then the inspect verdict is "never-reprojected"

  Scenario: A Story with no published version
    Given the record has no published version
    When the editor inspects the Story
    Then the inspect verdict is "not-published"

  Scenario: Everything current
    Given the record is published at version 7 and the stored page was rendered from version 7
    And the edge serves version 7
    When the editor inspects the Story
    Then the inspect verdict is "current"

  Scenario: Inspecting without fix invalidates nothing
    Given the record is published at version 7 and the stored page was rendered from version 7
    And the edge serves a copy last modified before the page was stored
    When the editor inspects the Story
    Then the inspect run invalidated nothing

  Scenario: Fix purges exactly the page's paths and looks again
    Given the record is published at version 7 and the stored page was rendered from version 7
    And the edge serves a copy last modified before the page was stored
    When the editor inspects the Story and asks to fix it
    Then the inspect run invalidated exactly the Story's three paths
    And the inspect verdict is "current"
