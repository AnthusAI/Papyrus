Feature: A reader picks one cadence of the same items and every item reaches them by exactly one route
  Lists that carry the same items at different cadences (every new item, a daily summary) form a family: they name the same family in the list settings. A reader
  holds at most one list of a family at a time, and choosing another moves them. A list that names no family is its own family, so the curated weekly newsletter,
  which may repeat items by design, is not touched by a reader's daily or every-item choice.

  A switch between the cadences of a family takes effect at the next period start of the family's periodic list, not at the moment the reader clicks. Until then
  the reader stays on the list they were on, so an item published after a noon switch and before the next period start still reaches them, through that list. The
  first summary of the new list covers the period that starts then. So every item reaches the reader by exactly one route: nothing twice and nothing missed. The
  preferences page shows the reader's choice at once, while mail keeps following the membership.

  Every membership records when it began (its "since") and, once the reader has moved off, when it ended (its "until"). An every-item message goes to the readers who
  are members at the moment it is sent. A periodic summary goes to the readers who were members at the start of its period, so a reader who has moved on since still
  receives the summary they were due. The rule is Caducus's and is applied where the reader's lists are written, so it holds for subscribing, confirming, saving
  preferences and the one-click unsubscribe alike. Nothing here is sent anywhere: the mailer is a recorder and every address is a placeholder.

  Background:
    Given a site with the lists "every-item" and "daily" in the family "new-stories" and the list "weekly" in its own family
    And the daily list is sent at "06:00" in "America/New_York"

  Scenario: Choosing the daily summary shows as the reader's choice at once and begins at the next period start
    Given the reader has confirmed "every-item" on "2026-11-03T15:00:00Z"
    When the reader chooses "daily" on the preferences page on "2026-11-04T17:00:00Z"
    Then the preferences page shows "daily" on and "every-item" off
    And the reader's membership of "every-item" ends at "2026-11-05T11:00:00Z"
    And the reader's membership of "daily" begins at "2026-11-05T11:00:00Z"

  Scenario: A reader cannot ask for two lists of one family at once
    When the reader subscribes to "every-item" and "daily" together
    Then the function answers 400 "one_cadence_per_family"
    And nothing is mailed to the reader

  Scenario: Two new lists of one family cannot be added from the preferences page either
    Given the reader has confirmed "weekly" on "2026-11-03T15:00:00Z"
    When the reader saves the preferences "weekly", "every-item" and "daily" on "2026-11-04T17:00:00Z"
    Then the function answers 400 "one_cadence_per_family"
    And the reader is still on "weekly" and nothing else

  Scenario: Saving preferences that hold an old and a new list of one family moves the reader
    Given the reader has confirmed "every-item" on "2026-11-03T15:00:00Z"
    And the reader has confirmed "weekly" on "2026-11-03T15:00:00Z"
    When the reader saves the preferences "every-item", "daily" and "weekly" on "2026-11-04T17:00:00Z"
    Then the preferences page shows "daily" and "weekly" on and "every-item" off
    And the reader's membership of "daily" begins at "2026-11-05T11:00:00Z"

  Scenario: An item published after a noon switch and before the next period start reaches the reader by exactly one route
    Given the reader has confirmed "every-item" on "2026-11-03T15:00:00Z"
    And the story "Morning story" is published and sent at "2026-11-04T14:00:00Z"
    When the reader chooses "daily" on the preferences page on "2026-11-04T17:00:00Z"
    And the story "Afternoon story" is published and sent at "2026-11-04T18:00:00Z"
    And the daily summary scheduled for "2026-11-05T06:00" local time is sent
    And the story "Next morning story" is published and sent at "2026-11-05T12:00:00Z"
    And the daily summary scheduled for "2026-11-06T06:00" local time is sent
    Then the reader has the message for "Morning story" once
    And the reader has the message for "Afternoon story" once
    And the reader has no message for "Next morning story" as it happened
    And the reader has only the daily summary scheduled for "2026-11-06T06:00" local time and not the one scheduled for "2026-11-05T06:00" local time

  Scenario: A reader who stays on every-item gets each item once and no summary
    Given the reader has confirmed "every-item" on "2026-11-03T15:00:00Z"
    When the story "Morning story" is published and sent at "2026-11-04T14:00:00Z"
    And the story "Afternoon story" is published and sent at "2026-11-04T18:00:00Z"
    And the daily summary scheduled for "2026-11-06T06:00" local time is sent
    Then the reader has the message for "Morning story" once
    And the reader has the message for "Afternoon story" once
    And the reader has no daily summary

  Scenario: Switching from the daily summary to every item waits for the next period start in the same way
    Given the reader has confirmed "daily" on "2026-11-03T15:00:00Z"
    When the reader chooses "every-item" on the preferences page on "2026-11-04T17:00:00Z"
    And the story "Afternoon story" is published and sent at "2026-11-04T18:00:00Z"
    And the daily summary scheduled for "2026-11-05T06:00" local time is sent
    And the story "Next morning story" is published and sent at "2026-11-05T12:00:00Z"
    Then the reader has no message for "Afternoon story" as it happened
    And the reader has the daily summary scheduled for "2026-11-05T06:00" local time
    And the reader has the message for "Next morning story" once

  Scenario: A summary of a past period still reaches a reader who has since moved off
    Given the reader has confirmed "daily" on "2026-11-03T15:00:00Z"
    And the reader chooses "every-item" on the preferences page on "2026-11-04T17:00:00Z"
    When the time is "2026-11-05T12:00:00Z"
    And the daily summary scheduled for "2026-11-05T06:00" local time is sent
    Then the reader has the daily summary scheduled for "2026-11-05T06:00" local time

  Scenario: A reader who joins the daily summary after a period started does not get that period's summary
    Given the reader has confirmed "weekly" on "2026-11-03T15:00:00Z"
    When the reader saves the preferences "daily" and "weekly" on "2026-11-04T17:00:00Z"
    And the daily summary scheduled for "2026-11-05T06:00" local time is sent
    Then the reader has no daily summary

  Scenario: Choosing the old list again before the switch begins cancels it
    Given the reader has confirmed "every-item" on "2026-11-03T15:00:00Z"
    And the reader chooses "daily" on the preferences page on "2026-11-04T17:00:00Z"
    When the reader chooses "every-item" on the preferences page on "2026-11-04T19:00:00Z"
    And the story "Next morning story" is published and sent at "2026-11-05T12:00:00Z"
    Then the reader is on "every-item" and nothing else
    And the reader has the message for "Next morning story" once

  Scenario: The curated weekly newsletter is its own family and is unaffected by the switch
    Given the reader has confirmed "weekly" on "2026-11-01T15:00:00Z"
    And the reader has confirmed "every-item" on "2026-11-03T15:00:00Z"
    When the reader chooses "daily" on the preferences page on "2026-11-04T17:00:00Z"
    And the weekly issue scheduled for "2026-11-09T04:00" local time is sent
    And the weekly issue scheduled for "2026-11-16T04:00" local time is sent
    Then the reader has the weekly issue scheduled for "2026-11-09T04:00" local time
    And the reader has the weekly issue scheduled for "2026-11-16T04:00" local time
    And the reader's membership of "weekly" began at "2026-11-01T15:00:00Z" and has no end

  Scenario: A reader on the weekly newsletter and the daily summary gets both
    Given the reader has confirmed "weekly" on "2026-11-02T15:00:00Z"
    When the reader saves the preferences "daily" and "weekly" on "2026-11-03T15:00:00Z"
    And the daily summary scheduled for "2026-11-06T06:00" local time is sent
    And the weekly issue scheduled for "2026-11-16T04:00" local time is sent
    Then the reader has the daily summary scheduled for "2026-11-06T06:00" local time
    And the reader has the weekly issue scheduled for "2026-11-16T04:00" local time

  Scenario: The one-click link of the list a reader is leaving does not touch the list they chose
    Given the reader has confirmed "every-item" on "2026-11-03T15:00:00Z"
    And the story "Morning story" is published and sent at "2026-11-04T14:00:00Z"
    When the reader chooses "daily" on the preferences page on "2026-11-04T17:00:00Z"
    And the mail provider posts the one-click unsubscribe from the message for "Morning story"
    Then the preferences page shows "daily" on and "every-item" off
    And the reader is not suppressed

  Scenario: The one-click unsubscribe from the list a reader holds leaves only that list
    Given the reader has confirmed "every-item" on "2026-11-03T15:00:00Z"
    And the reader has confirmed "weekly" on "2026-11-03T15:00:00Z"
    And the story "Morning story" is published and sent at "2026-11-04T14:00:00Z"
    When the mail provider posts the one-click unsubscribe from the message for "Morning story"
    Then the reader is still on "weekly" and nothing else

  Scenario: Joining the daily summary again after leaving begins a new membership at once, because there is no other list of the family to move from
    Given the reader has confirmed "daily" on "2026-11-03T15:00:00Z"
    And the reader has confirmed "weekly" on "2026-11-03T15:00:00Z"
    And the reader turns off "daily" on "2026-11-04T10:00:00Z"
    When the reader saves the preferences "daily" and "weekly" on "2026-11-04T17:00:00Z"
    Then the reader's membership of "daily" begins at "2026-11-04T17:00:00Z"
    And the reader's membership of "weekly" began at "2026-11-03T15:00:00Z" and has no end

  Scenario: A family with no periodic list moves a reader at once
    Given a site whose lists "first" and "second" form a family with no periodic list
    And the reader has confirmed "first" on "2026-11-03T15:00:00Z"
    When the reader chooses "second" on the preferences page on "2026-11-04T17:00:00Z"
    Then the reader's membership of "first" ends at "2026-11-04T17:00:00Z"
    And the reader's membership of "second" begins at "2026-11-04T17:00:00Z"

  Scenario: Two lists of one family cannot both be periodic
    When a list settings document names a daily and a weekly list of the family "new-stories"
    Then the settings are refused saying a family has one periodic list

  Scenario: Two new lists of one family cannot share a cadence
    When a list settings document names two daily lists of the family "new-stories"
    Then the settings are refused saying a family has one list for each cadence
