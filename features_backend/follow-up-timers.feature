Feature: A due time on a record raises one wake
  Every wait is a named time on the record that waits: `dueAt`, with `waitingFor` (a Delivery already carries both). One helper turns that time into a
  timer: a one-shot entry in the site's schedule group that fires once, puts a wake on the site's wake queue, and then deletes itself. Setting a new
  time moves the entry, so a record never has two; clearing the time deletes it. Nothing polls and nothing sweeps for work that is late.

  The wake's key names the record and the due time (`<agent>|<record>|<due time>|due`), so the same time delivered twice is one wake, and a new time is
  a different wake. The timer does nothing but put the wake on the queue. The run that follows reads the record again, and a record that no longer
  waits for the time the wake names (the time moved, the time was cleared, the record is done or gone) does nothing. The helper's entries are named
  `follow-up-` and a digest of the record, so the schedule reconciler for agent definitions never touches them.

  Scheduled publishing is the same mechanism with a different target: its per-version entries are made by the same helper, still in the account's default
  group and still delivering to the content-actions function, and a scheduled Story still publishes at its time.

  Background:
    Given the site "distinctive" with its follow-up timers and its wake queue
    And the delivery "delivery-1" waits for "rate-limit" until "2026-11-17T09:00:00Z"

  Scenario: A due time raises one wake at that time
    When the site's follow-up timer is set for "delivery-1"
    Then the site's timers hold exactly 1 entry
    And the entry fires once at "2026-11-17T09:00:00Z" in UTC and is deleted after it runs
    And the follow-up entry's only target is the wake queue of "distinctive"
    When the time "2026-11-17T09:00:00Z" arrives
    Then the follow-up queue holds 1 message
    And the follow-up message's wake key is "deliver|delivery-1|2026-11-17T09:00:00Z|due"
    And the follow-up message says in words that "delivery-1" was waiting until "2026-11-17T09:00:00Z" for "rate-limit"
    And the site's timers hold exactly 0 entries

  Scenario: The same time delivered twice is one wake
    Given the site's follow-up timer is set for "delivery-1"
    When the time "2026-11-17T09:00:00Z" arrives
    And the scheduler delivers the entry for "delivery-1" again
    Then the follow-up queue holds 1 message

  Scenario: A moved time raises one wake at the new time
    Given the site's follow-up timer is set for "delivery-1"
    When the delivery "delivery-1" now waits for "rate-limit" until "2026-11-17T12:00:00Z"
    And the site's follow-up timer is set for "delivery-1"
    Then the site's timers hold exactly 1 entry
    When the time "2026-11-17T09:00:00Z" arrives
    Then the follow-up queue holds 0 messages
    When the time "2026-11-17T12:00:00Z" arrives
    Then the follow-up queue holds 1 message
    And the follow-up message's wake key is "deliver|delivery-1|2026-11-17T12:00:00Z|due"

  Scenario: A cleared time raises none
    Given the site's follow-up timer is set for "delivery-1"
    When the delivery "delivery-1" no longer waits
    And the site's follow-up timer is set for "delivery-1"
    Then the site's timers hold exactly 0 entries
    When the time "2026-11-17T12:00:00Z" arrives
    Then the follow-up queue holds 0 messages

  Scenario: Clearing a time whose entry already fired and deleted itself is not an error
    Given the site's follow-up timer is set for "delivery-1"
    And the time "2026-11-17T09:00:00Z" arrives
    When the delivery "delivery-1" no longer waits
    And the site's follow-up timer is set for "delivery-1"
    Then nothing went wrong

  Scenario: Two records have two entries and two wakes
    Given the delivery "delivery-2" waits for "budget" until "2026-11-17T09:00:00Z"
    When the site's follow-up timer is set for "delivery-1"
    And the site's follow-up timer is set for "delivery-2"
    Then the site's timers hold exactly 2 entries
    When the time "2026-11-17T09:00:00Z" arrives
    Then the follow-up queue holds 2 messages

  Scenario: A wake for a record that still waits for that time goes on
    Given the site's follow-up timer is set for "delivery-1"
    And the time "2026-11-17T09:00:00Z" arrives
    When the run reads the record for the wake on the queue
    Then the record still waits for "2026-11-17T09:00:00Z" and the run goes on

  Scenario: A wake for a record whose time moved does nothing
    Given the site's follow-up timer is set for "delivery-1"
    And the time "2026-11-17T09:00:00Z" arrives
    When the delivery "delivery-1" now waits for "rate-limit" until "2026-11-17T12:00:00Z"
    And the run reads the record for the wake on the queue
    Then the run does nothing and says "the record now waits until 2026-11-17T12:00:00Z, which has its own wake"

  Scenario: A wake for a record whose time was cleared does nothing
    Given the site's follow-up timer is set for "delivery-1"
    And the time "2026-11-17T09:00:00Z" arrives
    When the delivery "delivery-1" no longer waits
    And the run reads the record for the wake on the queue
    Then the run does nothing and says "the record waits for nothing now"

  Scenario: A wake for a record that is gone does nothing
    Given the site's follow-up timer is set for "delivery-1"
    And the time "2026-11-17T09:00:00Z" arrives
    When the delivery "delivery-1" is deleted
    And the run reads the record for the wake on the queue
    Then the run does nothing and says "the record is gone"

  Scenario: The agent schedule reconciler never touches a follow-up
    Given the site's follow-up timer is set for "delivery-1"
    Then the entry's name does not begin with "agent-"

  Scenario: A time that is not a UTC instant is refused and writes nothing
    Given the delivery "delivery-1" waits for "rate-limit" until "tomorrow morning"
    When the site's follow-up timer is set for "delivery-1"
    Then the follow-up is refused because a due time is a UTC instant
    And the site's timers hold exactly 0 entries

  Scenario: Scheduled publishing still publishes on time, through the same helper
    Given the publication's time zone is America/New_York
    And Sam may publish on this site
    And it is 10 November 2026 at 15:00 UTC
    And the Story "Robots in the warehouse" has 3 versions
    And Sam scheduled version 3 for 13 November 2026 at 09:00 New York time
    When 13 November 2026 at 14:00 UTC arrives
    Then version 3 is published
    And the Story's published time is the moment it went live
    And scheduled publishing makes its timer through the follow-up helper, in the default group, delivering to the content-actions function
    And moving or clearing that timer uses the helper's replace and delete
