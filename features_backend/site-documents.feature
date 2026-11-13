Feature: Site documents
  A site's configuration is data: the site settings, the brand and the navigation. Each is a document with versions.
  DynamoDB holds only the catalogue, a SiteDocument row that points at the live version and a SiteDocumentVersion row for
  every saved version; the document itself is a JSON object in S3 under tenants/<tenant>/site/<kind>/<version>.json.
  A save writes the new object first, then the version row, and only then moves the live pointer, with a check that the
  pointer is still where the save started. So a save that stops half way is never live. Restoring an older version is
  a new save that carries the old content, so history is never rewritten. Nothing uses the store yet; the site store
  and the projection come next.

  Scenario: A brand change is a new version
    Given "alpha" has brand version 3
    When an admin saves new colours
    Then version 4 is written to S3 and SiteDocument points at it only after the object exists

  Scenario: An older version can be restored
    Given "alpha" has brand versions 1 to 4
    When an admin restores version 2
    Then version 5 is written with version 2's content

  Scenario: A save that fails before the pointer moves leaves the old version live
    Given "alpha" has brand version 3
    When a save of new colours fails after its object is written but before the pointer moves
    Then the brand is still version 3 and the failed save is not live
    And the next save takes version 4 and replaces the leftover object
