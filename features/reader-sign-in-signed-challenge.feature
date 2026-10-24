@brand-agnostic
Feature: Reader sign-in carries Prospectus's signed challenge
  Prospectus can sign its sign-in challenges instead of storing them. A signed challenge exists only as the
  challenge token it returned, so a site that sends back just the challenge ID is told the challenge does not
  exist and the reader cannot sign in. These scenarios are verified by scripts/test-prospectus-sign-in-routes.ts and
  scripts/test-prospectus-site-identity.ts, which run in CI.

  Scenario: The signed challenge token survives the trip through the browser unchanged
    Given Prospectus answers the challenge request with a nonce and a signed challenge token
    When a reader starts signing in
    Then the Google sign-in request carries the challenge nonce
    And the sealed pending cookie holds the challenge token byte for byte and stays well under the 4 KB cookie limit

  Scenario: The callback resolves the sign-in with the signed token
    Given a reader who started signing in with a signed challenge
    When Google returns the reader to the callback
    Then Prospectus is asked to resolve the sign-in with the challenge token alone
    And the reader is signed in and returned to the page they started from

  Scenario: A Prospectus that stores challenges still works
    Given Prospectus answers the challenge request with a challenge ID and no token
    When the reader's sign-in is completed
    Then Prospectus is asked to resolve the sign-in with the challenge ID

  Scenario: A reload during sign-in starts a fresh challenge
    Given a reader who starts signing in twice
    Then each start seals its own challenge into the pending cookie
