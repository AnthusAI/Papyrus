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

  Scenario: A session saved by the earlier CLI in the macOS Keychain is still read and renewed
    Given a macOS Keychain that already holds an earlier CLI session under service "papyrus-newsroom-oauth" and the site's key
    When a CLI session for that site is used 25 simulated hours later
    Then the shared login library read it from that same service and key
    And it renewed with the stored refresh token without interactive sign-in
    And the renewed session is saved back under that same service and key

  Scenario: Without a keyring or a memory agent, login fails with guidance and saves nothing
    Given a Linux machine with no Secret Service, no kernel keyring and no memory agent
    When the user tries to sign in to a site
    Then sign-in fails saying how to start the memory agent for "papyrus-newsroom-oauth"
    And no session or token file was written

  Scenario: Two sites stay isolated in one secure store
    Given a macOS Keychain shared by two signed-in sites on the same sign-in pool
    When the user renews the first site's session
    Then only the first site's own refresh token was sent to the provider
    And signing out of the first site leaves the second site signed in
