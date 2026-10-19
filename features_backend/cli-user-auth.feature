Feature: Renewable normal-user CLI authentication
  A newsroom user signs in once with Google and uses their existing permissions without AWS SSO.

  Scenario: Initial login uses the publication identity
    Given a configured newsroom login with an isolated OAuth provider and secure store
    When the user completes the CLI Google sign-in
    Then the CLI identifies the user and publication without exposing tokens

  Scenario: An already registered localhost callback can be used
    Given a configured newsroom login with an isolated OAuth provider and secure store
    And its registered callback uses literal localhost
    When the user completes the CLI Google sign-in
    Then the CLI identifies the user and publication without exposing tokens

  Scenario: Renew across process restarts after 24 simulated hours
    Given a configured newsroom login with an isolated OAuth provider and secure store
    When the user completes the CLI Google sign-in
    And a restarted CLI session is used after 25 simulated hours
    Then it renews without interactive sign-in
    And this evidence is labelled simulated rather than elapsed live testing

  Scenario: Revocation cannot become broader operator access
    Given a configured newsroom login with an isolated OAuth provider and secure store
    When the user completes the CLI Google sign-in
    And the provider confirms the renewable session was revoked
    Then the CLI requires login without falling back to IAM

  Scenario: Offline logout is honest
    Given a configured newsroom login with an isolated OAuth provider and secure store
    When the user completes the CLI Google sign-in
    And logout cannot reach the provider
    Then local secrets are removed and remote revocation is unconfirmed
