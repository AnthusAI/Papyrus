Feature: The site owner decides what is announced
  Announcing is the most public thing a site does, so it is off until the owner turns it on, and the owner sets
  the bar, the budget and the pause. Every rule is enforced where the settings are saved, not only on the page.

  Background:
    Given a site "mom" with a fake X and encrypted parameter storage
    And an admin named "ryan" and an editor named "ellie"

  Scenario: Everything is off until the owner turns it on
    When ellie reads the announcement settings
    Then the mode is "off"
    And the minimum rating is 5 stars
    And the budget is not set
    And announcements are not paused

  Scenario: The floor cannot go below the site's quality floor
    When ryan saves the announcement settings with a minimum of 2 stars
    Then the announcement request is refused with "Announcements can't go below your quality floor of 3 stars."

  Scenario: Dry run needs a connected account
    When ryan saves the announcement settings with the mode "dry_run"
    Then the announcement request is refused with "Connect an X account before choosing Dry run or On."

  Scenario: Dry run is allowed once the account is connected
    Given ryan connected the X account "mom_test"
    When ryan saves the announcement settings with the mode "dry_run"
    Then the mode is "dry_run"

  Scenario: On also needs the label confirmation and a budget
    Given ryan connected the X account "mom_test"
    When ryan saves the announcement settings with the mode "on"
    Then the announcement request is refused with "Confirm that the account shows X's Automated label before turning announcements on."
    When ryan confirms the Automated label and saves the mode "on"
    Then the announcement request is refused with "Enter a budget per X billing cycle before turning announcements on."
    When ryan confirms the Automated label, sets the budget to 10 and saves the mode "on"
    Then the mode is "on"
    And the budget is 10

  Scenario: Only Articles and Posts can be announced, never References
    When ryan saves the announcement settings with the story types "reference"
    Then the announcement request is refused with "Choose at least one kind of Story to announce (Articles or Posts). References are never announced."

  Scenario: Limiting to sections and raising the bar are saved
    When ryan saves the announcement settings with a minimum of 4 stars in the sections "Security"
    Then the minimum rating is 4 stars
    And the sections are "Security"

  Scenario: The prices are editable and carry the date they were copied
    When ryan saves the price of a post with a link as 0.25 as of "2026-12-01"
    Then the price of a post with a link is 0.25 as of "2026-12-01"

  Scenario: Pausing stops everything and shows who and why
    When ryan pauses announcements
    Then announcements are paused with the reason "manual"
    And the pause names "ryan"
    When ryan resumes announcements
    Then announcements are not paused

  Scenario: An editor can read the settings but not change them
    When ellie tries to save the announcement settings with the mode "off"
    Then the announcement request is refused with "Your role cannot do this."
