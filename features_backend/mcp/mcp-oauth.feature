Feature: Site-bound authorization for hosted MCP
  A person grants a client access to one publication using their existing identity.

  Scenario: Authorization codes bind the client, redirect, resource and PKCE verifier
    Given a signed-in person authorizes a registered client for a publication
    When the client exchanges the code with a different redirect, resource or verifier
    Then the exchange is refused and the code remains unusable by that request

  Scenario: Reader identity requires the verified per-site subject
    Given a person has signed in through Prospectus
    When Prospectus has not returned a verified site subject
    Then reader authorization is unavailable

  Scenario: Staff authorization uses the person's own credentials
    Given an authenticated newsroom staff member
    When the member authorizes a client
    Then the grant carries that member's user-scoped credentials
    And no operator credentials are substituted

  Scenario: Refresh tokens rotate and replay revokes the grant
    Given a client holds a valid refresh token
    When it refreshes and then replays the old token
    Then the replay is refused and the grant is revoked

  Scenario: Grants cannot outlive upstream authorization
    Given upstream authorization expires in one hour
    When the person authorizes a client
    Then the grant expires no later than that upstream authorization
    And no grant lasts more than seven days

  Scenario: Revocation and publication isolation
    Given a client holds a grant for one publication
    When the grant is revoked or presented to another publication
    Then the grant cannot authorize access

  Scenario: Malformed bearer values never reach grant storage
    Given a client holds a grant for one publication
    When malformed tokens are presented
    Then they are refused without looking them up

  Scenario: A client refreshes throughout the fixed seven-day grant
    Given a client holds a grant with a seven-day deadline
    When it refreshes every fifteen minutes until the deadline
    Then each previous access token fails immediately after rotation
    And the deadline never moves and the grant fails at the deadline

  Scenario: A spent refresh cannot be replayed by an unrelated client or publication
    Given a client holds a valid refresh token
    When the token is rotated and an unrelated client or publication replays it
    Then the successor remains usable until a real replay revokes it

  Scenario: A staff grant needs both credentials from the verified session
    Given an authenticated newsroom staff member
    When the member's ID credential is absent
    Then no staff grant is issued

  Scenario: Access rotates only until the browser authorization expires
    Given a client holds a grant backed by a one-hour browser session
    When access expires and the client refreshes it until that session expires
    Then access works after rotation but no refresh extends the original deadline
