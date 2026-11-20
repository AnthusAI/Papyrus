Feature: Publishing a Story starts a rebuild of the reader site
  Publishing through the content actions starts a rebuild of the static reader site, using the function's own IAM permission and
  no webhook address or token. A rebuild already waiting is not queued a second time, and a rebuild that cannot be started never
  makes the publish itself fail.

  Scenario: Publishing starts a reader rebuild
    Given a content actions backend with a reader app and no pending build
    When the editor saves and publishes an article
    Then the publish response reports a started rebuild
    And exactly 1 build was started

  Scenario: Publishing while a build is pending does not queue another
    Given a content actions backend with a reader app and a pending build
    When the editor saves and publishes an article
    Then the publish response reports the rebuild was skipped because a build is pending
    And exactly 0 builds were started

  Scenario: A failed trigger does not fail the publish
    Given a content actions backend with a reader app whose build start fails
    When the editor saves and publishes an article
    Then the publish response is ok
    And the publish response reports a rebuild error
    And a published item exists
