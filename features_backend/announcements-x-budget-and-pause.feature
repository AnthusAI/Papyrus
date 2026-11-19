Feature: Announcements never cost more than the owner allowed
  Every post with a link costs money at X. The owner sets a budget for each X billing cycle and a price list copied from X, can pause everything, and sees why anything
  waits. The pause and the budget are Caducus's guard, asked before every post: a refusal closes the attempt and the Delivery waits as Blocked with its reason, and the next
  try is the next attempt. A refusal for the budget also pauses announcements with the reason and tells the editors. A pause the budget caused ends by itself when there is
  room again; a pause a person made never does. Spend is one counter for each account and billing cycle, raised for every charge Caducus records.

  Background:
    Given a site whose quality floor is 3 stars
    And an X account "mom" is connected to the site
    And the announce agent may act without a person's release
    And the site announces Articles rated 5 stars with a budget of $10.00, in Dry run
    And the mode is On

  Scenario: Pausing stops everything and says who and why
    When the owner pauses announcements
    And a 5-star Article is published
    And the deliver side sends the X Delivery
    And Caducus posts it for $0.20
    And the deliver side reads what Caducus recorded
    Then the X Delivery reads "Blocked: paused"
    And the settings say the pause was made by "ryan" with the reason "Paused by hand."
    And nothing was posted

  Scenario: Resuming puts back what waited, and the next try is the next attempt
    Given announcements are paused
    And a 5-star Article is published
    And the deliver side sends the X Delivery
    And Caducus posts it for $0.20
    And the deliver side reads what Caducus recorded
    When the owner resumes announcements
    And the deliver side sends what is due
    Then the X Delivery reads "Sending"
    And the events handed over are the Delivery's attempt 1 and attempt 2 events

  Scenario: Reaching the budget pauses with the reason
    Given $9.90 is already spent this cycle
    When a 5-star Article is published
    And the deliver side sends the X Delivery
    And Caducus posts it for $0.20
    And the deliver side reads what Caducus recorded
    Then the X Delivery reads "Blocked: budget reached"
    And announcements are paused with "Budget reached for this cycle"
    And the editors are told the budget was reached

  Scenario: Raising the budget lets the waiting Delivery go
    Given $9.90 is already spent this cycle
    And a 5-star Article is published
    And the deliver side sends the X Delivery
    And Caducus posts it for $0.20
    And the deliver side reads what Caducus recorded
    When the owner raises the budget to $20.00
    And the deliver side sends what is due
    Then the X Delivery reads "Sending"
    And announcements are no longer paused
    And the events handed over are the Delivery's attempt 1 and attempt 2 events

  Scenario: A pause a person made is never lifted by the budget
    Given announcements are paused
    When the owner raises the budget to $20.00
    Then announcements are still paused

  Scenario: A new billing cycle starts at zero
    Given $9.90 is already spent in the last cycle
    When a 5-star Article is published
    And the deliver side sends the X Delivery
    And Caducus posts it for $0.20
    And the deliver side reads what Caducus recorded
    Then the X Delivery reads "Sent"

  Scenario: An account that needs reconnecting sends nothing
    Given the account needs reconnecting
    When a 5-star Article is published
    And the deliver side tries to send the X Delivery
    Then the deliver side refuses saying "needs connecting again"
    And the Delivery has no attempts
    And the editors are told the account needs reconnecting

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
