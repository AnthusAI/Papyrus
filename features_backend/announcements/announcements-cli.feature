Feature: People and agents at a terminal manage announcements
  Agents work through the CLI and MCP, so every console action has the same operation
  behind it. Connecting the X account stays in the browser. The X app's keys are saved from the command line, with the secret read from the environment or standard input and never a flag. The Announcements themselves are read with
  where, recent and explain (announcement-list-lines.feature, announcement-explain.feature); the list and show commands of the old X row shape are gone.

  Background:
    Given a site whose quality floor is 3 stars
    And the announcement commands run against the site's backend

  Scenario: Settings are shown with the connected account
    When a person types "papyrus announcements settings show"
    Then the announcement command succeeds
    And the announcement answer shows mode "off" and the account "mom"

  Scenario: A rule the site enforces is refused with its sentence
    When a person types "papyrus announcements settings set --mode dry_run --min-stars 2 --story-types article"
    Then the announcement command fails with "settings_refused"
    And the announcement answer says "Announcements can't go below your quality floor of 3 stars."

  Scenario: An agent may not change the settings, at any rung
    When an AI agent types "papyrus announcements settings set --mode dry_run --min-stars 5"
    Then the announcement command fails with "blocked"

  Scenario: Settings are saved and shown
    When a person saves the announcement settings in Dry run at 5 stars with a budget of $10.00
    Then the announcement command succeeds
    And "papyrus announcements settings show" shows mode "dry_run" and minStars 5

  Scenario: Previewing a Story's announcement sends and records nothing
    Given the announcement settings are saved for the account "mom" in Dry run at 5 stars
    And a published 5-star Article "story-1"
    When a person types "papyrus announcements dry-run story-1"
    Then the announcement command succeeds
    And the announcement answer has the exact post with the tagged link and sent false
    And no Announcement or Delivery is recorded

  Scenario: A site with no writing guidelines says so in the preview
    Given the announcement settings are saved for the account "mom" in Dry run at 5 stars
    And a published 5-star Article "story-1"
    When a person types "papyrus announcements dry-run story-1" with no writing guidelines
    Then the announcement answer is not passed and says "This publication has no writing guidelines"

  Scenario: Pausing from the command line
    Given the announcement settings are saved for the account "mom" in Dry run at 5 stars
    When a person types "papyrus announcements pause"
    Then the announcement command succeeds
    And "papyrus announcements account status" shows paused true

  Scenario: A dry run of pause changes nothing
    Given the announcement settings are saved for the account "mom" in Dry run at 5 stars
    When a person types "papyrus announcements pause --dry-run"
    Then "papyrus announcements account status" shows paused false

  Scenario: The CLI never takes a secret
    When a person types "papyrus announcements settings set --client-secret abc"
    Then the announcement command fails with "invalid_input"

  Scenario: The X app keys are saved with the secret on standard input
    When a person types "papyrus announcements account set-app --client-id id-1" with the secret "secret-1" on standard input
    Then the announcement command succeeds
    And the site saved the X app "id-1" with the secret "secret-1"
    And the announcement answer does not contain "secret-1"

  Scenario: The X app keys are saved with the secret in the environment
    When a person types "papyrus announcements account set-app --client-id id-1" with the secret "secret-2" in the environment
    Then the site saved the X app "id-1" with the secret "secret-2"

  Scenario: Nothing is saved when the secret is missing
    When a person types "papyrus announcements account set-app --client-id id-1"
    Then the announcement command fails with "invalid_input"
    And the site saved no X app keys

  Scenario: A dry run saves nothing and never shows the secret
    When a person types "papyrus announcements account set-app --client-id id-1 --dry-run" with the secret "secret-3" on standard input
    Then the announcement command succeeds
    And the announcement answer does not contain "secret-3"
    And the site saved no X app keys

  Scenario: An agent may not save the X app keys
    When an AI agent types "papyrus announcements account set-app --client-id id-1" with the secret "secret-4" on standard input
    Then the announcement command fails with "blocked"
    And the site saved no X app keys

  Scenario: At a terminal the command asks for the ID and the hidden secret
    When a person types "papyrus announcements account set-app" at a terminal answering the ID "id-9" and the secret "secret-9" privately
    Then the announcement command succeeds
    And the site saved the X app "id-9" with the secret "secret-9"
    And the announcement answer does not contain "secret-9"
