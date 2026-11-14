Feature: A site owner connects the X account the site posts from
  The account and its keys belong to the site owner. The owner brings an X developer app and pays X for it.
  Papyrus keeps the keys in encrypted storage and never shows them again once they are entered. These
  scenarios run against a fake X, so nothing here touches the real X or spends a cent.

  Background:
    Given a site "mom" with a fake X and encrypted parameter storage
    And an admin named "ryan" and an editor named "ellie"

  Scenario: Entering the X app's keys shows the client id and never the secret
    When ryan saves the X app's client id "client-123" and client secret "s3cret-value"
    Then the answer shows the client id "client-123" and says the secret is saved
    And no answer to any request contains "s3cret-value"
    And the secret is stored encrypted at "/papyrus/mom/announcements/x/client-secret"

  Scenario: Only an admin can change the keys, and an editor can see the connection status
    When ellie tries to save the X app's client id "client-123" and client secret "s3cret-value"
    Then the announcement request is refused with "Your role cannot do this."
    And ellie can read the connection status

  Scenario: Connecting the account asks X for posting, reading, the profile and staying signed in
    Given ryan saved the X app's keys
    When ryan chooses Connect X account and approves at X as "mom_test"
    Then the page shows "Connected: @mom_test"
    And the permissions asked for were "tweet.write tweet.read users.read offline.access"
    And the sign-in used a PKCE challenge and the app's secret in the Authorization header
    And the refresh token is stored encrypted at "/papyrus/mom/announcements/x/1001/refresh-token"
    And no answer to any request contains "refresh-1"

  Scenario: A connection that did not start on this site is refused
    Given ryan saved the X app's keys
    When someone returns from X with a state this site never issued
    Then the announcement request is refused with "This connection did not start here. Choose Connect X account again."
    And no account is connected

  Scenario: An expired access token is replaced and the new refresh token is saved first
    Given ryan connected the X account "mom_test"
    And more than two hours pass
    When an announcement needs to post
    Then a new access token is obtained from X
    And the stored refresh token is the newest one X issued
    And the status shows a last refresh time

  Scenario: Two posts at the same moment cause one refresh
    Given ryan connected the X account "mom_test"
    And more than two hours pass
    And X takes a moment to answer a refresh
    When two announcements need to post at the same moment
    Then X was asked to refresh once
    And both posts use the same access token

  Scenario: A broken connection pauses announcements and says why
    Given ryan connected the X account "mom_test"
    And more than two hours pass
    And X refuses to refresh the token
    When an announcement needs to post
    Then the connection shows "Needs reconnecting"
    And announcements are paused with the reason "disconnected"
    And posting is refused with "X refused to refresh the token"

  Scenario: Disconnecting revokes the token at X and deletes it from our store
    Given ryan connected the X account "mom_test"
    When ryan chooses Disconnect
    Then X was asked to revoke the refresh token
    And the encrypted parameters of the account are gone
    And the page shows no connected account
    And announcements are paused with the reason "disconnected"

  Scenario: Reconnecting lifts the pause that disconnecting caused
    Given ryan connected the X account "mom_test"
    And ryan chooses Disconnect
    When ryan chooses Connect X account and approves at X as "mom_test"
    Then announcements are not paused

  Scenario: X's usage count is shown beside the connection
    Given ryan connected the X account "mom_test"
    When ellie reads X's usage
    Then the usage shows 12 posts counted and a cap of 2000
