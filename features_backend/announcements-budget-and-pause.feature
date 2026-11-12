Feature: Announcements never cost more than the owner allowed
  Every post with a link costs money at X. The owner sets a budget for each X billing
  cycle and a price list copied from X, can pause everything, and sees why anything waits.

  Background:
    Given a site whose quality floor is 3 stars
    And an X account "mom" is connected to the site
    And the site announces Articles rated 5 stars with a budget of $10.00, in Dry run

  Scenario: Pausing stops everything and says why
    When the owner pauses announcements with the reason "Checking the first posts"
    And a 5-star Article is published
    Then the Article is "Blocked: paused"
    And the settings say the pause was made by "ryan" with the reason "Checking the first posts"

  Scenario: Resuming announces what waited
    Given announcements are paused
    And a 5-star Article is published
    When the owner resumes announcements
    Then the Article is recorded as "Dry run: not sent"

  Scenario: Reaching the budget pauses with the reason
    Given $9.90 is already spent this cycle
    When a 5-star Article is published
    Then the Article is "Blocked: budget reached"
    And announcements are paused with "Budget reached for this cycle"
    And the editors are told the budget was reached

  Scenario: Raising the budget lets the waiting Story go
    Given $9.90 is already spent this cycle
    And a 5-star Article is published
    When the owner raises the budget to $20.00
    Then the Article is recorded as "Dry run: not sent"
    And announcements are no longer paused

  Scenario: A pause a person made is never lifted by the budget
    Given announcements are paused
    When the owner raises the budget to $20.00
    Then announcements are still paused

  Scenario: A new billing cycle starts at zero
    Given $9.90 is already spent in the last cycle
    When a 5-star Article is published
    Then the Article is recorded as "Dry run: not sent"

  Scenario: An account that needs reconnecting pauses announcements
    Given the account needs reconnecting
    When a 5-star Article is published
    Then the Article is "Blocked: account needs reconnecting"
    And announcements are paused

  Scenario: The guard Caducus asks refuses a post that would pass the budget
    Given $9.90 is already spent this cycle
    Then the guard refuses a $0.20 post with "Budget reached for this cycle"
    And the guard allows a $0.05 post

  Scenario: Each charge Caducus makes raises the spend
    When Caducus reports a $0.20 charge on the account
    And Caducus reports a $0.20 charge on the account
    Then the spend this cycle is $0.40

  Scenario: Spend is shown as a sentence
    Given $0.60 is already spent this cycle
    Then the standing reads "$0.60 spent of $10.00 this cycle"

  Scenario: A budget suggestion comes from the site's own pace
    Then 4 eligible Stories in 60 days at $0.20 a post suggests "At your pace, about 2 posts and $0.40 per month"
