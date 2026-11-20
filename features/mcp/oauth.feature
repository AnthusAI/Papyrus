Feature: Authorize an MCP client
  A person can grant a known client access using their verified site session.

  Scenario: A client discovers the authorization server
    Given an MCP site with a configured public client
    When the client reads OAuth metadata
    Then the metadata names the configured site and its endpoints

  Scenario: Consent binds a public client to an exact redirect
    Given an MCP site with a configured public client
    When a request has an unregistered redirect or does not use S256
    Then authorization is refused without issuing a code
    When a valid request is approved by a signed-in person
    Then the client receives a code at its registered redirect

  Scenario: A forged consent request cannot issue a code
    Given an MCP site with a configured public client
    When a consent submission has an invalid transaction or origin
    Then authorization is refused without issuing a code

  Scenario: Staff and reader identities come from verified sessions
    Given signed-in staff and reader sessions
    When each approves a valid client
    Then the server sends its verified identity and expiry to the token service

  Scenario: A signed-out reader can sign in and return to the pending consent
    Given an MCP site with a configured public client
    When a signed-out reader attempts to approve the client
    Then the reader can sign in and return to the pending consent

  Scenario: Discovery survives a consent configuration outage
    Given an MCP site with a configured public client
    When the consent sealing secret is unavailable
    Then metadata remains discoverable and consent reports how to recover

  Scenario: Authorization responses identify their issuer
    Given an MCP site with a configured public client
    When a person approves or denies a client request with state
    Then the redirect carries the configured issuer and the original state

  Scenario: A same-origin browser form can submit consent
    Given a valid authorization request and a signed-in person
    When the consent form is submitted from the configured origin
    Then the form permits the browser to send its origin without exposing cross-origin referrers
    And a null or foreign origin cannot issue a code

  Scenario: The browser reaches the registered client after consent
    Given a client has a registered HTTPS callback
    When a signed-in person submits consent
    Then the browser may follow the response to that callback
    And foreign origins and invalid CSRF tokens remain refused

  Scenario: A reader starts sign-in from a pending authorization
    Given a pending client authorization and a signed-out reader
    When the reader follows the clean sign-in link
    Then the site starts sign-in and returns to the pending consent
    And an expired transaction or disabled reader sign-in cannot start it
