Feature: A reader picks one cadence of the same items, so nobody gets an item twice
  Lists that carry the same items at different cadences (every new item, a daily summary) form a family: they name the same family in the list settings. A reader
  holds at most one list of a family at a time, and choosing another moves them. A list that names no family is its own family, so the curated weekly newsletter,
  which may repeat items by design, is not touched by a reader's daily or every-item choice.

  Every membership records when the reader joined (its "since"). An every-item message goes to the readers who are members at the moment it is sent. A periodic
  summary goes to the readers who were members at the start of its period, so a reader who moves from every item to the daily summary at noon has had that day's
  earlier items once, as they happened, and receives the first summary for the next period, not the one already under way.

  The rule is applied where the reader's lists are written, so it holds for subscribing, confirming, saving preferences and the one-click unsubscribe alike.
  Nothing here is sent anywhere: the mailer is a recorder and every address is a placeholder.

  Background:
    Given a site with the lists "every-item" and "daily" in the family "new-stories" and the list "weekly" in its own family
    And the daily list is sent at "06:00" in "America/New_York"

  Scenario: Choosing the daily summary removes every-item
    Given the reader has confirmed "every-item" on "2026-11-03T15:00:00Z"
    When the reader chooses "daily" on the preferences page on "2026-11-04T17:00:00Z"
    Then the reader is on "daily" and not on "every-item"
    And the reader's membership of "daily" has been since "2026-11-04T17:00:00Z"

  Scenario: A reader cannot ask for two lists of one family at once
    When the reader subscribes to "every-item" and "daily" together
    Then the function answers 400 "one_cadence_per_family"
    And nothing is mailed to the reader

  Scenario: Saving preferences that hold an old and a new list of one family moves the reader
    Given the reader has confirmed "every-item" on "2026-11-03T15:00:00Z"
    And the reader has confirmed "weekly" on "2026-11-03T15:00:00Z"
    When the reader saves the preferences "every-item", "daily" and "weekly" on "2026-11-04T17:00:00Z"
    Then the reader is on "daily" and "weekly" and not on "every-item"

  Scenario: A switch at noon gets no item twice
    Given the reader has confirmed "every-item" on "2026-11-03T15:00:00Z"
    And the story "Morning story" is published and sent at "2026-11-04T14:00:00Z"
    When the reader chooses "daily" on the preferences page on "2026-11-04T17:00:00Z"
    And the story "Afternoon story" is published and sent at "2026-11-04T18:00:00Z"
    Then the reader has the message for "Morning story" once and none for "Afternoon story"
    And the daily summary scheduled for "2026-11-05T06:00" local time does not reach the reader
    And the daily summary scheduled for "2026-11-06T06:00" local time reaches the reader

  Scenario: A reader who stays on every-item still gets each item once
    Given the reader has confirmed "every-item" on "2026-11-03T15:00:00Z"
    When the story "Morning story" is published and sent at "2026-11-04T14:00:00Z"
    And the story "Afternoon story" is published and sent at "2026-11-04T18:00:00Z"
    Then the reader has the message for "Morning story" once and for "Afternoon story" once
    And the daily summary scheduled for "2026-11-06T06:00" local time does not reach the reader

  Scenario: A reader on the weekly newsletter and the daily summary gets both
    Given the reader has confirmed "weekly" on "2026-11-02T15:00:00Z"
    When the reader saves the preferences "daily" and "weekly" on "2026-11-03T15:00:00Z"
    Then the reader is on "daily" and "weekly" and not on "every-item"
    And the weekly newsletter's membership of the reader is still since "2026-11-02T15:00:00Z"
    And the daily summary scheduled for "2026-11-05T06:00" local time reaches the reader
    And the weekly issue scheduled for "2026-11-16T04:00" local time reaches the reader

  Scenario: Choosing every-item moves a reader off the daily summary but not off the weekly newsletter
    Given the reader has confirmed "daily" on "2026-11-03T15:00:00Z"
    And the reader has confirmed "weekly" on "2026-11-03T15:00:00Z"
    When the reader saves the preferences "daily", "every-item" and "weekly" on "2026-11-04T17:00:00Z"
    Then the reader is on "every-item" and "weekly" and not on "daily"

  Scenario: The one-click link of the list a reader has left does not touch the list they chose
    Given the reader has confirmed "every-item" on "2026-11-03T15:00:00Z"
    And the story "Morning story" is published and sent at "2026-11-04T14:00:00Z"
    When the reader chooses "daily" on the preferences page on "2026-11-04T17:00:00Z"
    And the mail provider posts the one-click unsubscribe from the message for "Morning story"
    Then the reader is on "daily" and not on "every-item"
    And the reader's membership of "daily" has been since "2026-11-04T17:00:00Z"
    And the reader is not suppressed

  Scenario: The one-click unsubscribe from the list a reader holds leaves only that list
    Given the reader has confirmed "every-item" on "2026-11-03T15:00:00Z"
    And the reader has confirmed "weekly" on "2026-11-03T15:00:00Z"
    And the story "Morning story" is published and sent at "2026-11-04T14:00:00Z"
    When the mail provider posts the one-click unsubscribe from the message for "Morning story"
    Then the reader is on "weekly" and not on "every-item"
    And the reader's membership of "weekly" has been since "2026-11-03T15:00:00Z"

  Scenario: Joining the daily summary again after leaving begins a new membership
    Given the reader has confirmed "daily" on "2026-11-03T15:00:00Z"
    And the reader has confirmed "weekly" on "2026-11-03T15:00:00Z"
    And the reader turns off "daily" on "2026-11-04T10:00:00Z"
    When the reader saves the preferences "daily" and "weekly" on "2026-11-04T17:00:00Z"
    Then the reader's membership of "daily" has been since "2026-11-04T17:00:00Z"
    And the daily summary scheduled for "2026-11-05T06:00" local time does not reach the reader
