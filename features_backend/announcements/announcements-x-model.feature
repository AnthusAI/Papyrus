Feature: The X model is the Announcement and the Delivery, and the old row shape is gone
  X used to have a model of its own: one row for each Story and account, with the decision, the channel, the words, the post and the retries all welded together, and a round
  suffix on the event id for a retry. That row shape and its account index are deleted in the same change that moves X onto the Announcement and the Delivery. No live X row
  existed, so nothing was converted; any dry-run row of the old shape is not read by anything and is not carried over. A retry is the next attempt of the same Delivery, so no
  event id has a round suffix. The settings, the account connection and the spend counter are unchanged.

  Scenario: The old X model and its index are not in the data schema
    Then the data schema has no model named "Announcement"
    And the data schema has no index named "listAnnouncementsByAccountAndCreatedAt"
    And the data schema still has the models "AnnouncementDecision", "Delivery", "AnnouncementSpend", "XConnection" and "AnnouncementSettings"

  Scenario: The signed-in lane knows no index on the old model
    Then the GraphQL index definitions have no index named "announcementsByAccountAndCreatedAt"
    And the GraphQL models the lane can list have no model named "Announcement"

  Scenario: The old model cannot own an attachment
    Then no attachment owner kind maps to the model "Announcement"

  Scenario: The old code that wrote it is gone
    Then there is no module named "papyrus_content.announcements.store"
    And there is no module named "papyrus_content.announcements.engine"

  Scenario: A retry is the next attempt and carries no round suffix
    Given a site whose quality floor is 3 stars
    And an X account "mom" is connected to the site
    And the announce agent may act without a person's release
    And the site announces Articles rated 5 stars with a budget of $10.00, in Dry run
    And the mode is On
    And a 5-star Article is published
    And the deliver side sends the X Delivery
    And Caducus's guard refuses it with "Budget reached for this cycle"
    And the deliver side reads what Caducus recorded
    When the owner raises the budget to $50.00
    And the deliver side sends what is due
    Then the events handed over are the Delivery's attempt 1 and attempt 2 events
    And no event carries a round suffix
    And the X Delivery has no field "round"
