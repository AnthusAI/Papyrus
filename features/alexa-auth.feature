Feature: Alexa account linking verifies the linked account's access token
  A site may turn on optional account linking for its Alexa skill. Alexa then sends the Cognito access token of the linked account
  with each request. The skill trusts that token only after checking its signature, issuer, expiry, type and client, and a request
  that is not signed in is invited to link its account while public content stays available.

  Scenario: A valid linked token identifies the user
    When a request carries a token signed by the pool's key for the skill's client
    Then the skill knows the user's identifier, username, email and groups

  Scenario: A request without a token is not signed in
    When a request carries no access token
    Then the skill treats it as signed out

  Scenario: Tokens that must not be trusted are refused
    When a request carries an expired token
    Then the skill treats it as signed out
    When a request carries a token for a different client
    Then the skill treats it as signed out
    When a request carries a token from a different issuer
    Then the skill treats it as signed out
    When a request carries an ID token instead of an access token
    Then the skill treats it as signed out
    When a request carries a revoked or forged token
    Then the skill treats it as signed out

  Scenario: The pool and client come from the Lambda environment
    When the Lambda environment does not name the pool and client
    Then every token is refused as not configured
    When the site turned account linking off
    Then the skill has no token verifier

  Scenario: A signed-out request is invited to link its account
    When a signed-in intent runs without a linked account
    Then the response carries a link account card and tells the listener how to link
    And a signed-in listener is not shown the card
