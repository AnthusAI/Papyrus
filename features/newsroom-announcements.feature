Feature: The Announcements page lets the site owner connect X and decide what is announced
  Under Administration, an admin follows a plain setup guide, enters the keys of their own X developer app, connects the
  site's X account, sets the mode, the rules and the budget, and sees what would be posted. The demo workspace uses fixture
  data and never contacts X.

  @brand-agnostic
  Scenario: The page explains the setup in plain words
    Given I open the announcements page at 1440 by 1000
    Then the announcements page should show the section "Set up your X account"
    And the setup guide should say a paid X subscription does not include API access
    And the setup guide should list 6 steps
    And the callback address should end with "/settings/announcements/x/callback" and have a Copy button

  @brand-agnostic
  Scenario: Entering the keys shows the client ID and never the secret
    Given I open the announcements page at 1440 by 1000
    When I enter the client ID "client-123" and the client secret "s3cret-value" and save the keys
    Then the page should say "Secret saved"
    And the text "s3cret-value" should not appear anywhere on the page

  @brand-agnostic
  Scenario: Connecting the account shows its handle, permissions and refresh health
    Given I open the announcements page at 1440 by 1000
    When I enter the client ID "client-123" and the client secret "s3cret-value" and save the keys
    And I choose Connect X account
    Then the connection should read "Connected: @mom_test"
    And the permissions should include "tweet.write" and "offline.access"
    And the refresh health should read "Healthy"

  @brand-agnostic
  Scenario: Disconnecting pauses announcements and says why
    Given I open the announcements page at 1440 by 1000
    When I enter the client ID "client-123" and the client secret "s3cret-value" and save the keys
    And I choose Connect X account
    And I choose Disconnect
    Then the connection should read "No X account connected"
    And the pause text should say "the X account is not connected"

  @brand-agnostic
  Scenario: Everything is off by default and a mode that needs an account says so
    Given I open the announcements page at 1440 by 1000
    Then the mode "Off" should be selected
    When I choose the mode "Dry run"
    Then the page should list the blocker "Connect an X account first."

  @brand-agnostic
  Scenario: The minimum rating is never offered below the three-star floor
    Given I open the announcements page at 1440 by 1000
    Then the minimum rating choices should be "3 stars, 4 stars, 5 stars"
    And "5 stars" should be selected with the word Selected

  @brand-agnostic
  Scenario: Pausing shows who and why, and resuming clears it
    Given I open the announcements page at 1440 by 1000
    When I choose Pause announcements
    Then the pause text should say "paused by hand"
    When I choose Resume announcements
    Then the pause text should say "Posts follow the mode below."

  @brand-agnostic
  Scenario: A budget is a plain number, saved with the settings
    Given I open the announcements page at 1440 by 1000
    When I enter the budget 10 and save the settings
    Then the page should say "Saved."
    And the budget field should read "10"

  @brand-agnostic
  Scenario: The price table shows the date it was copied
    Given I open the announcements page at 1440 by 1000
    Then the price table should say "as of 12 Nov 2026"

  @brand-agnostic
  Scenario: A dry run list shows the exact post and says it was not sent
    Given I open the announcements page at 1440 by 1000
    Then the announcement "The machines that audit other machines" should read "Dry run: not sent"

  @brand-agnostic
  Scenario: The page fits a phone
    Given I open the announcements page at 375 by 812
    Then the announcements page should not scroll sideways
