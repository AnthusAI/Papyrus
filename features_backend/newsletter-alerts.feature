Feature: Publish-triggered newsletter alerts
  Publishing an item that matches an alert list's rule raises one alert for that list, however the item is published and
  however often it is republished, edited or announced again. An alert waits for an admin unless the list is allowed to
  send instantly. Unpublishing and reprojecting raise nothing.

  Background:
    Given a site with an alert list for the "rulings" section and 2 confirmed subscribers

  Scenario: Publishing a matching item creates one alert, exactly once
    When the editor publishes an article in the "rulings" section
    Then 1 alert is awaiting approval
    And the alert subject is "Hello"
    When the editor changes the article and publishes it again
    And the same announcement is delivered again
    Then 1 alert is awaiting approval
    And no alert email is sent

  Scenario: An item the rule does not match raises no alert
    When the editor publishes an article in the "notes" section
    Then no alert exists

  Scenario: A publish from the command line raises the same single alert
    When the command line publishes an article in the "rulings" section
    Then 1 alert is awaiting approval
    When the editor publishes the same article in the newsroom
    Then 1 alert is awaiting approval

  Scenario: Unpublishing and reprojecting raise nothing
    Given the editor publishes an article in the "rulings" section
    When the editor unpublishes the alert's article
    And the whole site is reprojected
    Then the newsletter was told about 1 publish
    And 1 alert is awaiting approval

  Scenario: An admin approves the alert and it is mailed once to each subscriber
    Given the editor publishes an article in the "rulings" section
    When an admin approves the alert for an hour from now
    And the schedule fires the send for the alert
    And the worker handles the alert's queued messages
    Then the alert is mailed to 2 subscribers
    And the alert is "sent"
    And no Item is published for the alert
