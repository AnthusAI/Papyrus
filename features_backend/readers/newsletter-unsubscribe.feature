Feature: Newsletter unsubscribe, preferences and suppression
  A subscriber can leave with one click from any message, choose lists on a preferences page, come back by ticking a list,
  and erase their data. Permanent bounces and complaints suppress an address for good, a bad run of bounces or
  complaints pauses the site's sending, and none of it needs an email address to travel in a link.

  Background:
    Given a site whose newsletter plugin offers the lists "weekly", "alerts-a" and "alerts-b"
    And "reader@example.com" is subscribed to "weekly" and "alerts-a"

  Scenario: One-click unsubscribe leaves every list and can be repeated
    When the subscriber unsubscribes from everything 2 times
    Then every answer is "unsubscribed"
    And the subscriber is "unsubscribed" and holds no list

  Scenario: Unsubscribing from one list leaves the others
    When the subscriber unsubscribes from "alerts-a"
    Then the subscriber is "confirmed" and holds only "weekly"

  Scenario: Ticking a list again re-subscribes without a new opt-in email
    Given the subscriber unsubscribes from everything
    When the subscriber saves preferences choosing "alerts-b"
    Then the subscriber is "confirmed" and holds only "alerts-b"
    And no new email was sent to the subscriber

  Scenario: The preferences page names the lists and masks the address
    When the subscriber opens preferences
    Then the address shows as "r***@example.com"
    And "weekly" and "alerts-a" are ticked and "alerts-b" is not

  Scenario: A permanent bounce suppresses the address
    When SES reports a "Permanent" bounce for the subscriber
    Then the address is suppressed because of "bounce"
    And the subscriber is "unsubscribed" and holds no list
    When a visitor asks for "weekly" with "reader@example.com"
    Then no new email was sent to the subscriber

  Scenario: A transient bounce only counts
    When SES reports a "Transient" bounce for the subscriber
    Then the address is not suppressed
    And the subscriber is "confirmed" and holds only "alerts-a,weekly"

  Scenario: A complaint suppresses the address
    When SES reports a complaint for the subscriber
    Then the address is suppressed because of "complaint"

  Scenario: Deliberately subscribing again lifts a bounce suppression
    Given SES reports a "Permanent" bounce for the subscriber
    When the subscriber saves preferences choosing "weekly"
    Then the address is not suppressed
    And SES was told to forget the address

  Scenario: Deleting my data removes every record
    Given the subscriber was sent issue "issue0001"
    When the subscriber deletes their data
    Then nothing is stored about the subscriber

  Scenario: Events that are not ours are ignored
    When SES reports a "Permanent" bounce with no subscriber tag
    Then the address is not suppressed

  Scenario: A bad bounce rate pauses sending until an admin resumes it
    When the bounce rate alarm goes off
    Then sending is paused and SES sending is turned off
    When an admin resumes sending
    Then sending is not paused and SES sending is turned on
