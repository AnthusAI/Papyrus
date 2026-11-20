Feature: A qualifying Story is a dry run that sends nothing, or an X Delivery that the one account worker sends once
  In Dry run the whole path runs and the exact post is built and checked, but nothing is sent and nothing is spent: the Delivery's state is dry run and its cost is 0. In On the
  Delivery goes through its channel account's one worker like every Delivery: an attempt is written before Caducus is called, Caducus posts it and records the post id and
  what it cost, and Papyrus learns the result by reading Caducus's record. The deliver side refuses to send anything while the site's mode is not On, so X stays off until the
  owner turns it on. Nothing in these specs reaches X: the channel is a stand-in that behaves as Caducus's contract says.

  Background:
    Given a site whose quality floor is 3 stars
    And an X account "mom" is connected to the site
    And the announce agent may act without a person's release
    And the site announces Articles rated 5 stars, in Dry run

  Scenario: Dry run builds the exact post and sends nothing
    When a 5-star Article "Can a system keep a secret from itself?" is published
    Then the X Delivery reads "Dry run: not sent"
    And the post in the Delivery's words ends with the Article's link tagged utm_source=x, utm_medium=social and utm_campaign=announcement
    And the post in the Delivery's words weighs no more than 280
    And nothing was handed to the X channel
    And nothing was spent
    And the Delivery has no due time

  Scenario: A dry run is never sent, even by the deliver side
    Given a 5-star Article is published
    And the mode is On
    When the deliver side sends what is due
    Then nothing was handed to the X channel
    And the X Delivery reads "Dry run: not sent"

  Scenario: X stays off until the owner turns it on
    Given the mode is On
    And a 5-star Article is published
    And the owner turns the mode Off
    When the deliver side tries to send the X Delivery
    Then the deliver side refuses saying "not turned on"
    And nothing was handed to the X channel

  Scenario: On hands the post to the X channel through one attempt and waits for Caducus
    Given the mode is On
    When a 5-star Article is published
    And the deliver side sends the X Delivery
    Then the X Delivery reads "Sending"
    And exactly one event was handed to the X channel under the Delivery's first attempt id
    And no event carries a round suffix

  Scenario: The result Caducus records is read onto the Delivery
    Given the mode is On
    And a 5-star Article is published
    And the deliver side sends the X Delivery
    When Caducus posts it for $0.20
    And the deliver side reads what Caducus recorded
    Then the X Delivery reads "Sent"
    And the X Delivery has a post id and a cost of 0.20
    And the spend this cycle is $0.20

  Scenario: Sending the same Delivery again posts once
    Given the mode is On
    And a 5-star Article is published
    And the deliver side sends the X Delivery
    And Caducus posts it for $0.20
    And the deliver side reads what Caducus recorded
    When the deliver side sends the X Delivery
    Then the deliver side says the Delivery is not waiting to be sent
    And exactly one event was handed to the X channel under the Delivery's first attempt id

  Scenario: X refuses the post and the refusal is kept
    Given the mode is On
    And X will refuse posts with "403 Forbidden"
    And a 5-star Article is published
    And the deliver side sends the X Delivery
    When Caducus posts it for $0.20
    And the deliver side reads what Caducus recorded
    Then the X Delivery reads "Failed"
    And the Delivery's last attempt says "Refused" with the code "403 Forbidden"

  Scenario: The history says who did what and when
    Given the mode is On
    And a 5-star Article is published
    And the deliver side sends the X Delivery
    And Caducus posts it for $0.20
    When the deliver side reads what Caducus recorded
    Then the history of the X Delivery reads "drafted for x", "attempt 1 started" and "attempt 1 sent", each with a time and an actor

  Scenario: Reading an account's Deliveries never scans a table
    Given a 5-star Article is published
    When the account's X Deliveries are listed
    Then they were read through the account index only
