Feature: The site owner decides what is announced
  Announcing on X is the most public thing a site does, so it is off until the owner
  turns it on, and the owner sets the bar. Only Stories are announced, only on a human
  rating, and a Story is announced once however many events mention it.

  Background:
    Given a site whose quality floor is 3 stars
    And an X account "mom" is connected to the site

  Scenario: Nothing is announced until the owner turns announcements on
    Given the site never turned announcements on
    When a 5-star Article is published
    Then nothing is announced
    And no announcement is listed

  Scenario: Only the Stories that reach the bar are announced
    Given the site announces Articles rated 5 stars, in Dry run
    When a 4-star Article is published
    Then nothing is announced
    And no announcement is listed

  Scenario: The bar cannot go below the quality floor
    When the owner sets the announcement minimum to 2 stars
    Then the announcement settings are refused with "Announcements can't go below your quality floor of 3 stars."

  Scenario: Unrated Stories never qualify
    Given the site announces Articles rated 5 stars, in Dry run
    When an unrated Article is published
    Then nothing is announced

  Scenario: Only the Story types the owner chose are announced
    Given the site announces Articles rated 5 stars, in Dry run
    When a 5-star Post is published
    Then nothing is announced

  Scenario: A section limit is respected
    Given the site announces Articles rated 5 stars in the "security" section, in Dry run
    When a 5-star Article in the "hardware" section is published
    Then nothing is announced
    When a 5-star Article in the "security" section is published
    Then the Article is recorded as "Dry run: not sent"

  Scenario: A Story that is not published is not announced
    Given the site announces Articles rated 5 stars, in Dry run
    When a 5-star Article is saved as a draft
    Then nothing is announced

  Scenario: A Story rated after it is published is announced when it reaches the bar
    Given the site announces Articles rated 5 stars, in Dry run
    And a published 4-star Article
    When an editor rates the Article 5 stars
    Then the Article is recorded as "Dry run: not sent"

  Scenario: A new version never announces again
    Given the site announces Articles rated 5 stars, in Dry run
    And an announced Article
    When the Article is announced again because a corrected version was published
    Then there is still exactly one announcement for it

  Scenario: On needs the Automated label confirmed
    When the owner turns the mode On without confirming the Automated label
    Then the announcement settings are refused with "Confirm that the account shows X's Automated label before turning announcements on."

  Scenario: On needs a budget
    When the owner turns the mode On without a budget
    Then the announcement settings are refused with "Enter a budget per X billing cycle before turning announcements on."

  Scenario: A retired Story is not announced
    Given the site announces Articles rated 5 stars, in Dry run
    And a retired 5-star Article
    When the Article is announced
    Then nothing is announced
