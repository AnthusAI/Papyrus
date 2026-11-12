Feature: People and agents at a terminal manage announcements
  Agents work through the CLI and MCP, so every console action has the same operation
  behind it. Connecting the X account stays in the browser, and no secret is ever a flag.

  Background:
    Given a site whose quality floor is 3 stars
    And the announcement commands run against the site's backend

  Scenario: Settings are shown with the quality floor
    When a person types "papyrus announcements settings show"
    Then the announcement command succeeds
    And the announcement answer shows mode "off" and a quality floor of 3

  Scenario: A person sets the rules and sees every problem at once
    When a person types "papyrus announcements settings set --mode on --min-stars 2"
    Then the announcement command fails with "settings_refused"
    And the problems name minStars, storyTypes, accountId, budget, billingCycleDay, prices and labelConfirmed

  Scenario: An agent may not change the settings
    When an agent types "papyrus announcements settings set --mode dry_run --min-stars 5"
    Then the announcement command fails with "human_required"

  Scenario: Settings are saved and shown
    When a person saves the announcement settings for the account "mom" in Dry run at 5 stars with a budget of $10.00
    Then the announcement command succeeds
    And "papyrus announcements settings show" shows mode "dry_run" and minStars 5

  Scenario: Previewing a Story's announcement sends and records nothing
    Given the announcement settings are saved for the account "mom" in Dry run at 5 stars
    And a published 5-star Article "story-1"
    When a person types "papyrus announcements dry-run story-1"
    Then the announcement command succeeds
    And the announcement answer has the exact post with the tagged link and sent false
    And no announcement row is recorded

  Scenario: A site with no writing guidelines says so in the preview
    Given the announcement settings are saved for the account "mom" in Dry run at 5 stars
    And a published 5-star Article "story-1"
    When a person types "papyrus announcements dry-run story-1" with no writing guidelines
    Then the announcement answer is not passed and says "This publication has no writing guidelines"

  Scenario: Listing and showing an announcement
    Given the announcement settings are saved for the account "mom" in Dry run at 5 stars
    And a published 5-star Article "story-1" that was announced
    When a person types "papyrus announcements list"
    Then the announcement list has one announcement labelled "Dry run: not sent"
    When a person types "papyrus announcements show story-1"
    Then the announcement answer has the announcement and its stored post text

  Scenario: Showing a Story that was never announced
    Given the announcement settings are saved for the account "mom" in Dry run at 5 stars
    When a person types "papyrus announcements show nothing-here"
    Then the announcement command fails with "not_found"

  Scenario: Pausing from the command line
    Given the announcement settings are saved for the account "mom" in Dry run at 5 stars
    When a person types "papyrus announcements pause --reason Checking"
    Then the announcement command succeeds
    And "papyrus announcements account status" shows paused true

  Scenario: A dry run of pause changes nothing
    Given the announcement settings are saved for the account "mom" in Dry run at 5 stars
    When a person types "papyrus announcements pause --dry-run"
    Then "papyrus announcements account status" shows paused false

  Scenario: The CLI never takes a secret
    When a person types "papyrus announcements settings set --client-secret abc"
    Then the announcement command fails with "invalid_input"
