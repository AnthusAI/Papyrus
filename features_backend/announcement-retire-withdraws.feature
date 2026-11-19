Feature: Retiring a Story takes back what was announced about it
  When `papyrus stories retire` retires a Story, every Announcement that is now only about retired Stories is withdrawn, Delivery by Delivery, the way
  `papyrus announcements withdraw` does it. A Delivery that has not gone is stopped and nothing public changes. A post that already went on X is deleted by the site's own
  X channel, which the signed-in command line does not hold: the command says so for that Delivery, by id, and the Delivery stays sent, so nothing ever claims a post
  was taken back while it is still out. A roundup that still has a live Story is left alone. Undoing a retirement touches nothing.

  Background:
    Given a site whose quality floor is 3 stars
    And an X account "mom" is connected to the site
    And the announce agent may act without a person's release
    And the site announces Articles rated 5 stars with a budget of $10.00, in Dry run
    And the mode is On

  Scenario: A Delivery that has not gone is stopped
    Given an announced Article
    When the Article is retired with `papyrus stories retire`
    Then the X Delivery reads "Withdrawn"
    And the retire command printed "withdrew" for the X Delivery

  Scenario: A post that already went is reported and stays sent
    Given an announced Article
    And the X Delivery was sent and Caducus posted it for $0.20
    When the Article is retired with `papyrus stories retire`
    Then the X Delivery reads "Sent"
    And the retire command printed "NOT withdrawn" for the X Delivery, saying it needs the site's own X channel

  Scenario: A Story nobody announced prints nothing
    Given a published 5-star Article "quiet"
    When the Article is retired with `papyrus stories retire`
    Then the retire command printed nothing about announcements

  Scenario: A roundup that still has a live Story stays
    Given an announced Article
    And a roundup Announcement about that Article and a second live Article
    When the Article is retired with `papyrus stories retire`
    Then the roundup's Delivery is not withdrawn
