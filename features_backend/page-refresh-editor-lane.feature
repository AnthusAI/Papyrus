Feature: Signed-in editors refresh pages without AWS credentials
  A signed-in editor has no AWS credentials, so the command asks the newsroom's
  own refreshSitePages mutation, which runs the same operations in the
  content-actions function with the function's rights. An explicit refresh
  always invalidates when asked, even on a site whose default is not to
  invalidate on Save. A re-render of the whole site can outlast a request, so it
  is scheduled and the answer says so.

  Scenario: The signed-in command refreshes a page through the newsroom
    Given a content actions backend with an s3-projection publication
    And the edge reports invalidation ids and statuses
    And the editor publishes a new article
    When a signed-in editor runs the page refresh command "refresh --path /articles/hello.html"
    Then the page refresh command exits with status 0
    And the edge distribution was asked to invalidate "/articles/hello.html", "/articles/hello" and "/articles/hello.md"
    And the page refresh command output lists the CloudFront invalidation id with its status

  Scenario: The signed-in command refreshes a Story's pages
    Given a content actions backend with an s3-projection publication
    And the edge reports invalidation ids and statuses
    And the editor publishes a new article
    When a signed-in editor refreshes the published article through the newsroom
    Then the newsroom answer is ok
    And the edge distribution was asked to invalidate "/articles/hello.html" and "/"

  Scenario: An explicit refresh invalidates on a site that does not invalidate on Save
    Given a content actions backend with an s3-projection publication whose saves do not invalidate
    And the edge reports invalidation ids and statuses
    And the editor publishes a new article
    When a signed-in editor runs the page refresh command "refresh --path /articles/hello.html"
    Then the page refresh command exits with status 0
    And the edge distribution was asked to invalidate "/articles/hello.html"

  Scenario: Re-rendering the whole site from the editor lane is scheduled
    Given a content actions backend with an s3-projection publication
    And the edge reports invalidation ids and statuses
    And the editor publishes a new article
    When a signed-in editor runs the page refresh command "rerender --all"
    Then the page refresh command exits with status 0
    And the page refresh command output says the re-render was scheduled
    And the scheduled task re-renders the whole site and invalidates what it wrote

  Scenario: The scheduled re-render writes the pages and purges exactly them
    Given a content actions backend with an s3-projection publication
    And the edge reports invalidation ids and statuses
    And the editor publishes a new article
    And a signed-in editor runs the page refresh command "rerender --all"
    When the scheduled re-render task runs
    Then the site bucket holds "articles/hello.html"
    And the edge distribution was asked to invalidate "/articles/hello.html"

  Scenario: A site that does not project pages has no edge cache to refresh
    Given a content actions backend without a publication
    When a signed-in editor runs the page refresh command "refresh --path /articles/hello.html"
    Then the page refresh command exits with status 2
    And the page refresh command output says the site does not project its pages
