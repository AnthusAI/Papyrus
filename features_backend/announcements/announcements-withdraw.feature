Feature: Withdrawing a Delivery takes it back where it can be taken back, and says who did
  Withdraw is the one operation that can delete a public post. What has not gone is simply stopped and nothing public changes. A post on X that went is deleted through
  Caducus's x channel (a deletion is never blocked by a pause or the budget), and the Delivery records who withdrew it and what the post cost in all. A channel that cannot
  take its message back, a sent email or a post a person made by hand, is refused in words and the Delivery stays sent: it never says it was withdrawn while the message is
  still out. When every live Delivery of an Announcement is withdrawn the Announcement is too. A person may always withdraw. An agent may withdraw only when every Story
  the Announcement is about was retired; otherwise it is told a person must, and nothing is changed. The signed-in command line holds no rights on Caducus, so it can
  withdraw what never went and says so when a post would have to be deleted. Nothing here reaches X: the channel is a stand-in that behaves as Caducus's contract says.

  Background:
    Given a site whose quality floor is 3 stars
    And an X account "mom" is connected to the site
    And the announce agent may act without a person's release
    And the site announces Articles rated 5 stars with a budget of $10.00, in Dry run
    And the mode is On
    And a 5-star Article is published

  Scenario: A post that went is deleted and the Delivery says who withdrew it and what it cost
    Given the X Delivery was sent and Caducus posted it for $0.20
    When the person "ada" withdraws the X Delivery through the site's own X channel
    Then the post was deleted at X once
    And the X Delivery reads "Withdrawn"
    And the X Delivery's history says it was withdrawn by "ada"
    And the X Delivery's cost is 0.210
    And the Announcement is "withdrawn"

  Scenario: A Delivery that never went is stopped and no post is touched
    When the person "ada" withdraws the X Delivery through the site's own X channel
    Then nothing was handed to the X channel
    And no post was deleted
    And the X Delivery reads "Withdrawn"
    And the Announcement is "cancelled"

  Scenario: A dry run can be withdrawn too
    Given the owner turns the mode to Dry run and a second Story is published
    When the person "ada" withdraws the dry run
    Then the dry run Delivery reads "Withdrawn"
    And no post was deleted

  Scenario: Withdrawing twice changes nothing
    Given the X Delivery was sent and Caducus posted it for $0.20
    And the person "ada" withdraws the X Delivery through the site's own X channel
    When the person "bea" withdraws the X Delivery through the site's own X channel
    Then the post was deleted at X once
    And the X Delivery's history says it was withdrawn by "ada"
    And the X Delivery's history does not say "bea"

  Scenario: Deleting a post is retried safely after a crash
    Given the X Delivery was sent and Caducus posted it for $0.20
    And the channel deleted the post but the Delivery was not written
    When the person "ada" withdraws the X Delivery through the site's own X channel
    Then the post was deleted at X once
    And the X Delivery reads "Withdrawn"
    And the X Delivery's cost is 0.210

  Scenario: A Delivery with an attempt that has no answer is settled first
    Given the deliver side sends the X Delivery
    When the person "ada" withdraws the X Delivery through the site's own X channel
    Then the withdrawal is refused saying "attempt with no answer yet"
    And the X Delivery reads "Sending"

  Scenario: A sent email cannot be taken back
    Given an email Delivery on the same Announcement was sent
    When the person "ada" withdraws the email Delivery through the site's own X channel
    Then the withdrawal is refused saying "cannot be recalled"
    And the email Delivery reads "Sent"

  Scenario: A post a person made by hand is deleted by hand
    Given a manual X Delivery on another Announcement was recorded as posted by "ada"
    When the person "bea" withdraws the manual X Delivery through the site's own X channel
    Then the withdrawal is refused saying "deleted by hand"
    And the manual X Delivery reads "Sent"

  Scenario: The signed-in command line withdraws what never went
    When the person "ada" withdraws the X Delivery from the signed-in command line
    Then the withdrawal went through and the X Delivery reads "Withdrawn"

  Scenario: The signed-in command line cannot delete a post and says so
    Given the X Delivery was sent and Caducus posted it for $0.20
    When the person "ada" withdraws the X Delivery from the signed-in command line
    Then the withdrawal is refused as "service_unavailable" saying "site's own x channel"
    And the X Delivery reads "Sent"
    And no post was deleted

  Scenario: An agent is told a person must when the Story is not retired
    When the announce agent withdraws the X Delivery from the signed-in command line
    Then the withdrawal is refused as "human_required" saying "was retired"
    And the X Delivery reads "Ready"

  Scenario: An agent may withdraw when the Story was retired, and the Delivery records the agent
    Given the Article is retired
    When the announce agent withdraws the X Delivery from the signed-in command line
    Then the withdrawal went through and the X Delivery reads "Withdrawn"
    And the X Delivery's history says it was withdrawn by "announce"

  Scenario: An agent may delete the post of a retired Story through the site's own channel
    Given the X Delivery was sent and Caducus posted it for $0.20
    And the Article is retired
    When the announce agent withdraws the X Delivery through the site's own X channel
    Then the post was deleted at X once
    And the X Delivery reads "Withdrawn"

  Scenario: A Delivery a correction replaced is not withdrawn on its own
    Given the X Delivery was sent and Caducus posted it for $0.20
    And the person "ada" corrected the X Delivery with the words "A look at secrets, corrected." through the site's own X channel
    When the person "ada" withdraws generation 1 of the X Delivery through the site's own X channel
    Then the withdrawal is refused saying "replaced by a correction"
