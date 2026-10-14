Feature: Publishing through the content actions projects the site
  On a site with an s3-projection publication, publishing, saving a live item
  and unpublishing write the site inside the mutation. A projection failure
  never fails the save: the response says the item is not live and the failure
  is queued for repair.

  Scenario: Publishing writes the item page and reports where it is live
    Given a content actions backend with an s3-projection publication
    When the editor publishes a new article
    Then the publish response succeeds
    And the publish response says the item is live at "https://site.example/articles/hello.html"
    And the site bucket holds "articles/hello.html" with the published version
    And the edge distribution was invalidated for "/articles/hello.html"

  Scenario: Saving a live item projects the new version
    Given a content actions backend with an s3-projection publication
    And the editor publishes a new article
    When the editor saves the live article with a new body
    Then the site bucket page "articles/hello.html" contains "A new body."
    And the save response says the item is live

  Scenario: Saving a draft does not project
    Given a content actions backend with an s3-projection publication
    When the editor saves a draft article
    Then the site bucket holds no pages

  Scenario: Unpublishing deletes the page
    Given a content actions backend with an s3-projection publication
    And the editor publishes a new article
    When the editor unpublishes the article
    Then the site bucket no longer holds "articles/hello.html"

  Scenario: A projection failure does not fail the publish and is retried once, asynchronously
    Given a content actions backend with an s3-projection publication whose bucket rejects writes
    When the editor publishes a new article
    Then the publish response succeeds
    And the publish response says the item is not live
    And one asynchronous retry of the projection was scheduled for the item
    And nothing was queued on the projection dead letter queue
    And a published item exists

  Scenario: The scheduled retry repairs the page once the cause is gone
    Given a content actions backend with an s3-projection publication whose bucket rejects writes
    And the editor publishes a new article
    When the scheduled projection task runs with a working bucket
    Then the projection task succeeds
    And the site bucket holds "articles/hello.html" with the published version

  Scenario: A retry that fails again raises, so the event goes to the dead letter queue
    Given a content actions backend with an s3-projection publication whose bucket rejects writes
    And the editor publishes a new article
    When the scheduled projection task runs while the bucket still rejects writes
    Then the projection task raises so that Lambda retries it and then dead letters it

  Scenario: A change to what every page links to schedules the follow-up for the other item pages
    Given a content actions backend with an s3-projection publication
    When the editor publishes a new article
    Then the projection task for the other item pages was scheduled

  Scenario: Pages are cached briefly at the edge and the stale window is bounded
    Given a content actions backend with an s3-projection publication
    When the editor publishes a new article
    Then the page "articles/hello.html" is cached at the edge for 300 seconds with stale-while-revalidate

  Scenario: Switching invalidation off shortens the edge lifetime instead
    Given a content actions backend with an s3-projection publication
    And edge invalidation is switched off for the site
    When the editor publishes a new article
    Then the page "articles/hello.html" is cached at the edge for 60 seconds with stale-while-revalidate
    And the edge distribution was not invalidated

  Scenario: A failed purge leaves the page live and is retried on its own
    Given a content actions backend with an s3-projection publication
    And the edge distribution rejects invalidations
    When the editor publishes a new article
    Then the publish response succeeds
    And the publish response says the item is live but the edge was not purged
    And an asynchronous invalidation of the written pages was scheduled
    When the scheduled invalidation task runs with a working edge
    Then the projection task succeeds
    And the edge distribution was invalidated for "/articles/hello.html"

  Scenario: A backend deploy re-projects every published page
    Given a content actions backend with an s3-projection publication
    And the editor publishes a new article
    And the site bucket page "articles/hello.html" was removed
    When the deploy starts the "all" projection task
    Then the projection task succeeds
    And the site bucket holds "articles/hello.html" with the published version

  Scenario: The 404 page is stored with the headers CloudFront's error path needs
    Given a content actions backend with an s3-projection publication
    When the projection writes the pages "404.html" and "index.html"
    Then the stored page "404.html" has content type "text/html" and no cache header
    And the stored page "index.html" has content type "text/html; charset=utf-8" and a cache header

  Scenario: A backend deploy renders everything and reports that nothing drifted
    Given a content actions backend with an s3-projection publication
    And the editor publishes a new article
    And the site bucket page "articles/hello.html" was removed
    When the deploy starts the "deploy-render" projection task
    Then the projection task succeeds
    And the site bucket holds "articles/hello.html" with the published version
    And the deploy render report says nothing drifted

  Scenario: A backend deploy reports a page nothing publishes any more and deletes nothing
    Given a content actions backend with an s3-projection publication
    And the editor publishes a new article
    And a stray page "articles/ghost.html" in the site bucket
    When the deploy starts the "deploy-render" projection task
    Then the projection task succeeds
    And the deploy render report says the page "articles/ghost.html" drifted
    And the site bucket still holds "articles/ghost.html"

  Scenario: A backend deploy render that cannot write raises so the deploy fails
    Given a content actions backend with an s3-projection publication whose bucket rejects writes
    When the deploy starts the "deploy-render" projection task expecting failure
    Then the projection task raises so that Lambda retries it and then dead letters it

  Scenario: A site without a publication behaves as before
    Given a content actions backend without a publication
    When the editor publishes a new article
    Then the publish response succeeds
    And the publish response has no projection fields
