Feature: Deployment environment guards
  A staging deployment shows draft content to editors only and must never be
  indexed. A production deployment is the opposite.

  @staging
  Scenario: A staging deployment is not indexable and says so
    Given the site is served with SITE_ENV "staging"
    When I request the robots file
    Then the robots file should disallow everything
    When I open the newsroom as an anonymous visitor
    Then the page should declare noindex
    And the page should show the staging banner
    When I request the site root without a session
    Then I should be redirected to the newsroom sign-in

  @production-guards
  Scenario: A production deployment is indexable
    Given the site is served with SITE_ENV "production"
    When I request the robots file
    Then the robots file should allow everything
    When I open the newsroom as an anonymous visitor
    Then the page should not declare noindex
    And the page should not show the staging banner
