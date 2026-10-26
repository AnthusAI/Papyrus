Feature: Connect the existing newsroom editor to private chat
  A newsroom editor signs in with the site's Cognito client.
  Private chat also needs the same person's validated publishing Account.
  Connecting those sessions must never use a group claim as Account membership.

  Scenario: Connect the existing newsroom identity through the registered Google-only flow
    Given an editor has a valid signed newsroom access token but no Prospectus session
    When the editor connects private chat
    Then the server verifies the configured issuer, client, token use, expiry and editor role
    And the Google sign-in challenge is bound to that editor's verified subject
    And a callback for another subject is rejected before resolving a person

  Scenario: Select a publishing Account before opening a private channel
    Given the connected editor has not selected a publishing Account
    When the editor opens private chat
    Then the response requests validated publishing Account selection instead of another sign-in
    And no channel, message or model run is created

  Scenario: Preserve private transcript authorization after connecting identities
    Given an editor has matching newsroom and Prospectus identities and a selected Account
    When the editor opens private chat
    Then fresh Account membership and console permission are required
    And another editor cannot read the channel or its turn stream
