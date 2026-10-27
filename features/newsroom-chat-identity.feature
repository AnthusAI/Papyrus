Feature: Use the existing newsroom session for publication-local private chat
  Authorized editors use the existing publication login without another account connection.
  New conversations never adopt Prospectus or legacy history.

  Scenario: Verify the newsroom token
    Given an editor has a valid signed newsroom access token but no Prospectus session
    When the newsroom token verification suite runs
    Then the server verifies the configured issuer, client, token use, expiry and editor role

  Scenario: Isolate publication and editor history
    Given an editor has a valid signed newsroom access token but no Prospectus session
    When the Papyrus hosted chat endpoint contract suite runs
    Then the newsroom session alone opens publication-local private chat
    And another publication or editor cannot read the channel or its turn stream
    And expired credentials cannot read or send messages

  Scenario: Recover when the identity expires during an open conversation
    Given an editor has an open private conversation
    When the session expires during a send or a reply poll
    Then the old transcript and retry identity are removed from the panel
    And the editor can retry after signing into the newsroom

  Scenario: Clear old display when the newsroom identity changes
    Given an editor has an open private conversation
    When the session expires during a send or a reply poll
    Then the old transcript and retry identity are removed from the panel
    And the editor can retry after signing into the newsroom
