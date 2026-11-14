Feature: Every announcement can be traced
  If anything goes wrong on X we must be able to say exactly what was posted, by whom,
  when, at what cost, and why. The row is the catalog, the text is in the document store.

  Background:
    Given a site whose quality floor is 3 stars
    And an X account "mom" is connected to the site
    And the site announces Articles rated 5 stars, in Dry run
    And the mode is On

  Scenario: The Story shows its announcement
    Given a 5-star Article is published
    When Caducus posts it for $0.20
    And the announcement is refreshed
    Then looking the Story up shows account "mom", the post id, the time and the cost 0.20

  Scenario: The history records who did what and when
    Given a 5-star Article is published
    When Caducus posts it for $0.20
    And the announcement is refreshed
    Then the history reads "Handed to the X channel" and then "Posted", each with a time and an actor

  Scenario: Failures are kept with X's message and attempts
    Given X will refuse posts with "403 Forbidden"
    And a 5-star Article is published
    When Caducus posts it for $0.20
    And the announcement is refreshed
    Then the announcement keeps the message "403 Forbidden" and 1 attempt in its history

  Scenario: Reading an account's announcements never scans a table
    Given a 5-star Article is published
    When the account's announcements are listed
    Then they were read through the account index only

  Scenario: A guard refusal is final for its event and the next round has a new event id
    Given a 5-star Article is published
    When Caducus's guard refuses it with "Budget reached for this cycle"
    And the announcement is refreshed
    Then the announcement is "Blocked: budget reached"
    When the owner raises the budget to $50.00
    Then the announcement is "Posting"
    And the events handed over are the Article's event and its "r2" event
