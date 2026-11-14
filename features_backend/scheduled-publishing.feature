Feature: A Story goes live at the time an editor chose
  Our newsroom writes faster than we want to publish, so an editor picks when each Story goes out and the system publishes it then, without anyone at a keyboard.
  The schedule is kept on the version it publishes, so what goes out is exactly the text that was reviewed. One timer per scheduled version delivers an event to the
  site at the chosen moment, and the site claims the schedule before it publishes, so a duplicate event or a late event for an old time cannot publish twice or at
  the wrong time. Times are kept as a UTC instant and typed and shown in the publication's time zone. Nothing here sweeps for late work: a schedule that did not run
  is shown as overdue and an editor decides.

  Background:
    Given the publication's time zone is America/New_York
    And Sam may publish on this site
    And it is 10 November 2026 at 15:00 UTC

  Scenario: A scheduled version is published at its time
    Given the Story "Robots in the warehouse" has 3 versions
    And Sam scheduled version 3 for 13 November 2026 at 09:00 New York time
    When 13 November 2026 at 14:00 UTC arrives
    Then version 3 is published
    And the Story's published time is the moment it went live
    And the version records that it was published as scheduled by Sam
    And the Story no longer shows a schedule

  Scenario: The schedule is kept on the version in UTC, with one timer
    Given the Story "Robots in the warehouse" has 3 versions
    When Sam schedules version 3 for 13 November 2026 at 09:00 New York time
    Then version 3 carries the schedule: scheduled for 13 November 2026 at 14:00 UTC by Sam
    And one timer is set to deliver an event for version 3 at 14:00 UTC on 13 November 2026
    And the schedule index lists version 3 as scheduled

  Scenario: A newer version saved after scheduling is not published by surprise
    Given the Story "Robots in the warehouse" has 3 versions
    And Sam scheduled version 3 for 13 November 2026 at 09:00 New York time
    And the copywriting agent saved version 4 on 12 November 2026
    When 13 November 2026 at 14:00 UTC arrives
    Then no version of the Story goes live
    And the schedule says "A newer version was saved after this was scheduled. Schedule it again."
    And the site's editors are told

  Scenario: A new version does not inherit the schedule of the version before it
    Given the Story "Robots in the warehouse" has 3 versions
    And Sam scheduled version 3 for 13 November 2026 at 09:00 New York time
    When the copywriting agent saved version 4 on 12 November 2026
    Then version 4 carries no schedule
    And version 3 is still scheduled for 13 November 2026 at 14:00 UTC

  Scenario: Scheduling the newer version replaces the earlier schedule
    Given the Story "Robots in the warehouse" has 3 versions
    And Sam scheduled version 3 for 13 November 2026 at 09:00 New York time
    And the copywriting agent saved version 4 on 12 November 2026
    When Sam schedules version 4 for 14 November 2026 at 09:00 New York time
    Then the Story has exactly one schedule, on version 4, for 14 November 2026 at 14:00 UTC
    And version 3 carries no schedule

  Scenario: The same schedule firing twice publishes once
    Given the Story "Robots in the warehouse" has 3 versions
    And a scheduled version whose schedule fires twice at the same moment
    When both runs try to publish it
    Then it is published once
    And the second run stops without changing anything

  Scenario: A stale schedule does not publish after a change of time
    Given the Story "Robots in the warehouse" has 3 versions
    And Sam moved a schedule from 09:00 to 11:00 on 13 November 2026
    When a run for 09:00 arrives late
    Then no version of the Story goes live
    And version 3 is still scheduled for 13 November 2026 at 16:00 UTC

  Scenario: Publishing now ends the schedule
    Given the Story "Robots in the warehouse" has 3 versions
    And Sam scheduled version 3 for 13 November 2026 at 09:00 New York time
    When Sam publishes version 3 now
    Then version 3 is published
    And the schedule is removed and will not fire

  Scenario: Taking a Story down ends its schedule
    Given the Story "Robots in the warehouse" has 2 versions
    And Sam published version 2
    And the copywriting agent saved version 3 on 11 November 2026
    And Sam scheduled version 3 for 13 November 2026 at 09:00 New York time
    When Sam takes the Story down
    Then the schedule is removed and will not fire

  Scenario: Retiring a Story removes its schedule first
    Given a published Story "Old warehouse piece" with a scheduled newer version, and another published Story "Warehouse automation"
    When an editor retires "Old warehouse piece" into "Warehouse automation"
    Then the schedule of "Old warehouse piece" is removed before the Story is retired

  Scenario: A scheduled new version keeps the first publication date
    Given the Story "Robots in the warehouse" was first published on 4 November 2026 and has 5 versions
    And Sam scheduled version 5 for 14 November 2026 at 08:00 New York time
    When 14 November 2026 at 13:00 UTC arrives
    Then version 5 is published
    And the Story's published time is still 4 November 2026
    And the served version's published time is 14 November 2026 at 13:00 UTC

  Scenario: A missed schedule is visible, not silently handled
    Given the Story "Robots in the warehouse" has 3 versions
    And Sam scheduled version 3 for 13 November 2026 at 09:00 New York time
    When 13 November 2026 at 15:00 UTC arrives and nothing ran
    Then the schedule list shows "Robots in the warehouse" as overdue with its scheduled time
    And no version of the Story goes live

  Scenario: A schedule that cannot be delivered goes to a dead letter queue
    Given the Story "Robots in the warehouse" has 3 versions
    When Sam schedules version 3 for 13 November 2026 at 09:00 New York time
    Then the timer is a one-off in UTC that is removed after it runs
    And an event the timer cannot deliver goes to the site's dead letter queue

  Scenario: A time that does not exist is refused
    Given the Story "Robots in the warehouse" has 3 versions
    When Sam asks to schedule for 8 March 2026 at 02:30 New York time
    Then the scheduling request is refused with "That time does not exist on 8 March in New York. Pick another time."
    And nothing is scheduled

  Scenario: A time that happens twice must be chosen
    Given the Story "Robots in the warehouse" has 3 versions
    When Sam asks to schedule for 1 November 2026 at 01:30 New York time
    Then Sam is asked to choose between 01:30 EDT and 01:30 EST
    And nothing is scheduled

  Scenario: Choosing one of the two times with its offset schedules it
    Given the Story "Robots in the warehouse" has 3 versions
    When Sam schedules version 3 for the exact time 2027-11-07T01:30:00-04:00
    Then version 3 carries the schedule: scheduled for 7 November 2027 at 05:30 UTC by Sam

  Scenario: A time that has passed is refused
    Given the Story "Robots in the warehouse" has 3 versions
    When Sam asks to schedule for 9 November 2026 at 09:00 New York time
    Then the scheduling request is refused with "That time has passed."

  Scenario: Only people who may publish may schedule
    Given the Story "Robots in the warehouse" has 3 versions
    And Lee may edit but not publish
    When Lee tries to schedule a version
    Then the scheduling request is refused with "You can't publish on this site, so you can't schedule."
    And nothing is scheduled

  Scenario: Only the newest version can be scheduled
    Given the Story "Robots in the warehouse" has 3 versions
    When Sam asks to schedule version 2 for 13 November 2026 at 09:00 New York time
    Then the scheduling request is refused with "Version 2 is not the newest version of this Story. Schedule version 3."

  Scenario: A site that has not set its time zone says scheduling is off
    Given the publication has no time zone set
    And the Story "Robots in the warehouse" has 3 versions
    When Sam asks to schedule for 13 November 2026 at 09:00 New York time
    Then the scheduling request is refused with "This site has not turned scheduling on: set publication.timeZone in the site's backend settings and deploy."
