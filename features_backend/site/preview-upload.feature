Feature: A built site is uploaded to the private staging preview
  The staging preview serves a site that was already built, from a private preview location. Uploading a new build replaces
  everything that was there, so nothing stale is left behind, and a build with no files in it is refused instead of emptying the
  preview.

  Scenario: Uploading a built site replaces the preview prefix
    Given a built site with "index.html" and "articles/foo.html"
    And the bucket already holds "preview/old.html" and "media/keep.png"
    When I upload the built site to the preview prefix
    Then the bucket holds "preview/index.html" and "preview/articles/foo.html"
    And the bucket no longer holds "preview/old.html"
    And the bucket still holds "media/keep.png"

  Scenario: An empty build is refused
    Given an empty build directory
    And the bucket already holds "preview/old.html" and "media/keep.png"
    When I upload the built site to the preview prefix
    Then the upload is refused with "empty"
    And the bucket still holds "preview/old.html"
