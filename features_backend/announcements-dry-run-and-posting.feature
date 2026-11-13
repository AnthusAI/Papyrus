Feature: A qualifying Story is announced once, or shown as a dry run
  In Dry run the whole pipeline runs and the exact post is recorded, but nothing is sent
  and nothing is spent. In On the post is handed to the publication's X channel in
  Caducus, which posts it; the announcement then shows the post id and what it cost.

  Background:
    Given a site whose quality floor is 3 stars
    And an X account "mom" is connected to the site
    And the site announces Articles rated 5 stars, in Dry run

  Scenario: Dry run builds the exact post and sends nothing
    When a 5-star Article "Can a system keep a secret from itself?" is published
    Then the Article is recorded as "Dry run: not sent"
    And the recorded post ends with the Article's link tagged utm_source=x, utm_medium=social and utm_campaign=announcement
    And the recorded post weighs no more than 280
    And nothing was handed to the X channel
    And nothing was spent

  Scenario: The announcement shows the checks the draft passed
    When a 5-star Article is published
    Then the announcement lists the checks length, markup and facts as passed
    And the post text is kept in the document store, not on the row

  Scenario: On hands the post to the X channel and waits for Caducus
    Given the mode is On
    When a 5-star Article is published
    Then the announcement is "Posting"
    And exactly one event "story.announce:mom:" followed by the Article's lineage was handed to the X channel

  Scenario: The delivery's result is copied onto the announcement
    Given the mode is On
    And a 5-star Article is published
    When Caducus posts it for $0.20
    And the announcement is refreshed
    Then the announcement was posted with a post id and a cost of 0.20

  Scenario: Handing the same Story over twice posts once
    Given the mode is On
    And a 5-star Article is published
    When the Article is announced again because a corrected version was published
    Then exactly one event was handed to the X channel

  Scenario: X refuses the post and the refusal is kept
    Given the mode is On
    And X will refuse posts with "403 Forbidden"
    And a 5-star Article is published
    When Caducus posts it for $0.20
    And the announcement is refreshed
    Then the announcement failed with the message "403 Forbidden"

  Scenario: On without an X channel refuses to run
    Given the mode is On
    And the site has no X channel wired
    When a 5-star Article is published
    Then the announcement fails clearly because the X channel is not deployed
