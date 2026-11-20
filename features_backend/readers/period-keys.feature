Feature: A periodic issue belongs to the list's own period, and what was not sent carries forward
  The once-only key of a periodic Announcement is made from the list's local date, in the list's own time zone: the day for a daily list, the ISO week for a
  weekly one. It comes from the time the tick was scheduled for, never from UTC and never from when the run happened. So a run that is late, a tick that is
  delivered twice, a clock that moves for daylight saving time and a send time that changes all leave one issue for each period, and no period without one.

  An item is eligible for a list's next issue if it qualified since the list's last sent issue, not in "this calendar period". A period whose issue was never
  sent is not lost: when the next period's Announcement is made, the issue that never went is cancelled with the reason "not released before the next period;
  items carried forward", its waiting email is withdrawn, and its items are in the next issue. An issue that was sent is never cancelled and its items are not sent
  again. Nothing here sends an email: every Delivery is a record, and the specs read the records.

  Background:
    Given the site "mom" with its wake queue, its schedule group, its list settings and its announcement records
    And the agent "announce-lists" runs the procedure "announce_list", is switched on and is linked to the router publication of the site
    And "ryan" is an admin and "ellie" is an editor
    And the site's agent policy has the lists at the rung "prepare"

  Scenario: A run after midnight still belongs to its scheduled day
    Given the daily list "daily" is sent at "23:30" in "America/New_York"
    And these Stories are in the period
      | story      | stars | section | reviewed |
      | slow-water | 4     | science | yes      |
    When the scheduler fires the entry for the list "daily" for the time "2026-11-17T04:30:00Z"
    And the runner is delayed until "2026-11-17T06:10:00Z"
    And the runner handles the next scheduled message
    Then the Announcement "roundup:daily:2026-11-16" is planned for "2026-11-17T04:30:00Z"
    And the catalog holds the Announcements "roundup:daily:2026-11-16" and no others

  Scenario: A run in the next week still belongs to its scheduled week
    Given the weekly list "weekly" is sent on "sunday" at "23:30" in "America/New_York"
    And these Stories are in the period
      | story      | stars | section | reviewed |
      | slow-water | 4     | science | yes      |
    When the scheduler fires the entry for the list "weekly" for the time "2026-11-23T04:30:00Z"
    And the runner is delayed until "2026-11-23T15:00:00Z"
    And the runner handles the next scheduled message
    Then the Announcement "roundup:weekly:2026-W47" is planned for "2026-11-23T04:30:00Z"
    And the catalog holds the Announcements "roundup:weekly:2026-W47" and no others

  Scenario: Two ticks for one period make one Announcement and one Delivery
    Given the weekly list "weekly" is sent on "monday" at "04:00" in "America/New_York"
    And these Stories are in the period
      | story      | stars | section | reviewed |
      | slow-water | 4     | science | yes      |
    When the scheduler fires the entry for the list "weekly" for the time "2026-11-16T09:00:00Z"
    And the scheduler fires the entry for the list "weekly" for the time "2026-11-16T09:00:00Z" again
    And the scheduler fires the entry for the list "weekly" for the time "2026-11-18T09:00:00Z"
    And the runner handles every scheduled message
    Then the catalog holds the Announcements "roundup:weekly:2026-W47" and no others
    And the Announcement "roundup:weekly:2026-W47" is planned for "2026-11-16T09:00:00Z"
    And the catalog holds 1 Announcements and 1 Deliveries
    And the Announcement "roundup:weekly:2026-W47" is not cancelled

  Scenario: The clock going back makes one issue for the repeated hour
    Given the daily list "daily" is sent at "01:30" in "America/New_York"
    And these Stories are in the period
      | story      | stars | section | reviewed |
      | slow-water | 4     | science | yes      |
    When the scheduler fires the entry for the list "daily" for the time "2026-11-01T05:30:00Z"
    And the scheduler fires the entry for the list "daily" for the time "2026-11-01T06:30:00Z"
    And the scheduler fires the entry for the list "daily" for the time "2026-11-02T06:30:00Z"
    And the runner handles every scheduled message
    Then the catalog holds the Announcements "roundup:daily:2026-11-01" and "roundup:daily:2026-11-02" and no others
    And the Announcement "roundup:daily:2026-11-01" was decided for "2026-11-01T05:30:00Z", the first of the two ticks
    And the Announcement "roundup:daily:2026-11-02" is planned for "2026-11-02T06:30:00Z"

  Scenario: The clock going forward leaves no day without an issue
    Given the daily list "daily" is sent at "02:30" in "America/New_York"
    And these Stories are in the period
      | story      | stars | section | reviewed |
      | slow-water | 4     | science | yes      |
    When the scheduler fires the entry for the list "daily" for the time "2026-03-07T07:30:00Z"
    And the scheduler fires the entry for the list "daily" for the time "2026-03-08T07:30:00Z"
    And the scheduler fires the entry for the list "daily" for the time "2026-03-09T06:30:00Z"
    And the runner handles every scheduled message
    Then the catalog holds the Announcements "roundup:daily:2026-03-07", "roundup:daily:2026-03-08" and "roundup:daily:2026-03-09" and no others

  Scenario: A weekly list across the clock change keeps its weeks
    Given the weekly list "weekly" is sent on "sunday" at "01:30" in "America/New_York"
    And these Stories are in the period
      | story      | stars | section | reviewed |
      | slow-water | 4     | science | yes      |
    When the scheduler fires the entry for the list "weekly" for the time "2026-11-01T05:30:00Z"
    And the scheduler fires the entry for the list "weekly" for the time "2026-11-01T06:30:00Z"
    And the scheduler fires the entry for the list "weekly" for the time "2026-11-08T06:30:00Z"
    And the runner handles every scheduled message
    Then the catalog holds the Announcements "roundup:weekly:2026-W44" and "roundup:weekly:2026-W45" and no others

  Scenario: An issue that was never released is cancelled when the next period begins, and its items carry forward
    Given the weekly list "weekly" is sent on "monday" at "04:00" in "America/New_York"
    And these Stories are in the period
      | story        | stars | section | reviewed | qualified            |
      | slow-water   | 4     | science | yes      | 2026-11-12T15:00:00Z |
      | quiet-engine | 3     | science | yes      | 2026-11-20T15:00:00Z |
    When the scheduler fires the entry for the list "weekly" for the time "2026-11-16T09:00:00Z"
    And the runner handles the next scheduled message
    Then the Announcement "roundup:weekly:2026-W47" is planned for "2026-11-16T09:00:00Z"
    And the Announcement "roundup:weekly:2026-W47" is about the Stories "slow-water" and no others
    When the scheduler fires the entry for the list "weekly" for the time "2026-11-23T09:00:00Z"
    And the runner handles the next scheduled message
    Then the Announcement "roundup:weekly:2026-W47" is cancelled because "not released before the next period; items carried forward"
    And the Delivery of the Announcement "roundup:weekly:2026-W47" is withdrawn
    And the Announcement "roundup:weekly:2026-W48" is planned for "2026-11-23T09:00:00Z"
    And the Announcement "roundup:weekly:2026-W48" is about the Stories "slow-water" and "quiet-engine"
    And the run looked for Stories since the list's first issue
    And no email was sent

  Scenario: An issue that was released but never approved is carried forward in the same way
    Given the weekly list "weekly" is sent on "monday" at "04:00" in "America/New_York"
    And these Stories are in the period
      | story        | stars | section | reviewed | qualified            |
      | slow-water   | 4     | science | yes      | 2026-11-12T15:00:00Z |
      | quiet-engine | 3     | science | yes      | 2026-11-20T15:00:00Z |
    When the scheduler fires the entry for the list "weekly" for the time "2026-11-16T09:00:00Z"
    And the runner handles the next scheduled message
    And the due Announcements are released at "2026-11-16T09:00:00Z"
    And the scheduler fires the entry for the list "weekly" for the time "2026-11-23T09:00:00Z"
    And the runner handles the next scheduled message
    Then the Announcement "roundup:weekly:2026-W47" is cancelled because "not released before the next period; items carried forward"
    And the Delivery of the Announcement "roundup:weekly:2026-W47" is withdrawn
    And the Announcement "roundup:weekly:2026-W48" is about the Stories "slow-water" and "quiet-engine"
    And no email was sent

  Scenario: A period nobody ran for is not lost
    Given the weekly list "weekly" is sent on "monday" at "04:00" in "America/New_York"
    And these Stories are in the period
      | story      | stars | section | reviewed | qualified            |
      | slow-water | 4     | science | yes      | 2026-11-12T15:00:00Z |
    When the scheduler fires the entry for the list "weekly" for the time "2026-11-23T09:00:00Z"
    And the runner handles the next scheduled message
    Then the catalog holds the Announcements "roundup:weekly:2026-W48" and no others
    And the Announcement "roundup:weekly:2026-W48" is about the Stories "slow-water" and no others

  Scenario: An issue that was sent is never cancelled and its items are not sent again
    Given the weekly list "weekly" is sent on "monday" at "04:00" in "America/New_York"
    And these Stories are in the period
      | story        | stars | section | reviewed | qualified            |
      | slow-water   | 4     | science | yes      | 2026-11-12T15:00:00Z |
      | quiet-engine | 3     | science | yes      | 2026-11-18T15:00:00Z |
    When the scheduler fires the entry for the list "weekly" for the time "2026-11-16T09:00:00Z"
    And the runner handles the next scheduled message
    And the Delivery of the list "weekly" is approved and sent at "2026-11-16T09:05:00Z"
    And the scheduler fires the entry for the list "weekly" for the time "2026-11-23T09:00:00Z"
    And the runner handles the next scheduled message
    Then the Announcement "roundup:weekly:2026-W47" is not cancelled
    And the run looked for Stories since "2026-11-16T09:05:00Z"
    And the Announcement "roundup:weekly:2026-W48" is about the Stories "quiet-engine" and no others
