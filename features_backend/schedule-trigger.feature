Feature: An agent runs on a clock that comes from its definition
  A definition may name a schedule: a cron expression of five fields and a time zone. When a site deploys, right after the agent definitions are
  applied, a reconciler makes the site's EventBridge Scheduler group agree with the definitions that are live: one entry for each registered
  definition that names a schedule, is not retired and is switched on. An entry is named from the agent's id and lives in the site's schedule
  group (`papyrus-<site>-agent-schedules`). Its only target is the site's wake queue. Its message is a wake whose key is the agent, the word
  `schedule` and the time the entry was scheduled for, so a tick that is delivered twice is one wake and runs once.

  A timer does nothing else. It puts a wake on the queue; the runner then reads everything again (the site's policy, the pause, the definition),
  exactly as for a wake raised by a change. The entry carries the schedule's time zone by name and the local expression, never a UTC offset, so
  the scheduler keeps the local time across a clock change. Nobody makes an entry by hand: the group and the role the scheduler assumes are in the
  site's `agents` stack, and the entries are made by the deploy step. The role the scheduler assumes may send to the site's wake queue and
  nothing else.

  Nothing polls. The reconciler runs when the site deploys, and again whenever a person runs `papyrus agents schedules`; running it again with
  nothing changed writes nothing.

  Background:
    Given the site "distinctive" with its wake queue, its schedule group and the runner
    And the agent "rate-daily" runs the procedure "rate_items"
    And "rate-daily" is switched on and linked to the router publication of the site

  Scenario: A daily agent gets one entry that sends to the wake queue
    Given the definition of "rate-daily" says to run at "0 6 * * *" in "America/New_York"
    When the site deploys
    Then the schedule group holds exactly 1 entry
    And the entry for "rate-daily" says "cron(0 6 * * ? *)" in the time zone "America/New_York"
    And the entry has no flexible window
    And the entry's only target is the wake queue of "distinctive"
    And the entry's message group is the group the wake queue gives wakes of "rate-daily" about its schedule

  Scenario: The entry's message is a wake the runner accepts, keyed by the scheduled time
    Given the definition of "rate-daily" says to run at "0 6 * * *" in "America/New_York"
    And the site deploys
    When the scheduler fires the entry for the time "2026-11-17T11:00:00Z"
    Then the wake queue holds 1 scheduled message
    And the message's wake key is "rate-daily|schedule|2026-11-17T11:00:00Z"
    And the message says in words why it started
    When the runner runs the next scheduled message
    Then the site has 1 scheduled run record, made from the wake key
    And the scheduled procedure ran 1 time

  Scenario: A tick that is delivered twice runs once
    Given the definition of "rate-daily" says to run at "0 6 * * *" in "America/New_York"
    And the site deploys
    When the scheduler fires the entry for the time "2026-11-17T11:00:00Z"
    And the scheduler fires the entry for the time "2026-11-17T11:00:00Z" again
    And the runner runs every scheduled message
    Then the site has 1 scheduled run record, made from the wake key
    And the scheduled procedure ran 1 time

  Scenario: The next day's tick is a different wake and runs
    Given the definition of "rate-daily" says to run at "0 6 * * *" in "America/New_York"
    And the site deploys
    When the scheduler fires the entry for the time "2026-11-17T11:00:00Z"
    And the scheduler fires the entry for the time "2026-11-18T11:00:00Z"
    And the runner runs every scheduled message
    Then the site has 2 scheduled run records
    And the scheduled procedure ran 2 times

  Scenario: The local time holds across a clock change
    Given the definition of "rate-daily" says to run at "0 6 * * *" in "America/New_York"
    When the site deploys
    Then the entry for "rate-daily" says the local time and the zone, and no offset from UTC
    And the entry would fire at 6 in the morning in New York, which is "2026-03-07T11:00:00Z" the day before the clock change and "2026-03-09T10:00:00Z" the day after

  Scenario: A changed time takes effect at the next tick, on the same entry
    Given the definition of "rate-daily" says to run at "0 6 * * *" in "America/New_York"
    And the site deploys
    When the definition of "rate-daily" is changed to run at "30 7 * * 1-5" in "Europe/London"
    And the site deploys
    Then the schedule group holds exactly 1 entry
    And the entry for "rate-daily" says "cron(30 7 ? * 2-6 *)" in the time zone "Europe/London"

  Scenario: Removing the schedule from the definition removes the entry
    Given the definition of "rate-daily" says to run at "0 6 * * *" in "America/New_York"
    And the site deploys
    When the definition of "rate-daily" no longer names a schedule
    And the site deploys
    Then the schedule group holds exactly 0 entries

  Scenario: A definition gone from Git has no entry
    Given the definition of "rate-daily" says to run at "0 6 * * *" in "America/New_York"
    And the site deploys
    When the definition of "rate-daily" is removed from Git
    And the site deploys
    Then the schedule group holds exactly 0 entries

  Scenario: An agent that is switched off has no entry
    Given the definition of "rate-daily" says to run at "0 6 * * *" in "America/New_York"
    And the site deploys
    When "rate-daily" is switched off
    And the site deploys
    Then the schedule group holds exactly 0 entries
    When "rate-daily" is switched on
    And the site deploys
    Then the schedule group holds exactly 1 entry

  Scenario: No entry exists that a definition does not name
    Given the definition of "rate-daily" says to run at "0 6 * * *" in "America/New_York"
    And an entry "agent-left-over" that no definition names is in the schedule group
    When the site deploys
    Then the schedule group holds exactly 1 entry
    And the schedule group has no entry named "agent-left-over"

  Scenario: Entries of another kind in the group are left alone
    Given the definition of "rate-daily" says to run at "0 6 * * *" in "America/New_York"
    And a one-shot entry "due-story-17" of another helper is in the schedule group
    When the site deploys
    Then the schedule group holds the one-shot entry "due-story-17" and the entry for "rate-daily"

  Scenario: Deploying again with nothing changed writes nothing
    Given the definition of "rate-daily" says to run at "0 6 * * *" in "America/New_York"
    And the site deploys
    When the site deploys again
    Then the scheduler was asked to create, update or delete nothing

  Scenario: A preview says what would change and changes nothing
    Given the definition of "rate-daily" says to run at "0 6 * * *" in "America/New_York"
    When a person previews the schedules
    Then the preview says "rate-daily" would be created
    And the schedule group holds exactly 0 entries

  Scenario: A tick for a paused agent starts nothing and says why
    Given the definition of "rate-daily" says to run at "0 6 * * *" in "America/New_York"
    And the site deploys
    And the agent "rate-daily" is adopted onto the responsibility "rate" and the site's policy pauses it with the reason "an audit"
    When the scheduler fires the entry for the time "2026-11-17T11:00:00Z"
    And the runner runs every scheduled message
    Then the site has 1 scheduled run record, made from the wake key
    And the scheduled procedure ran 0 times
    And the run record says nothing started, with the reason "paused"
    And the scheduled message is deleted from the queue

  Scenario: A new agent is switched off, so it has no entry until a person switches it on
    Given the definition of "rate-daily" says to run at "0 6 * * *" in "America/New_York"
    And "rate-daily" is not switched on
    When the site deploys
    Then the schedule group holds exactly 0 entries

  Scenario: A switched-on agent that is not linked to a router publication is refused
    Given the definition of "rate-daily" says to run at "0 6 * * *" in "America/New_York"
    And "rate-daily" is switched on but names no router publication
    When the site deploys
    Then the deploy step stops with a message that says "rate-daily" needs a router publication
    And the scheduler was asked to create, update or delete nothing

  Scenario: An agent linked to another site's publication is refused
    Given the definition of "rate-daily" says to run at "0 6 * * *" in "America/New_York"
    And "rate-daily" is linked to the router publication "another-site"
    When the site deploys
    Then the deploy step stops with a message that says "rate-daily" belongs to another site
    And the scheduler was asked to create, update or delete nothing

  Scenario: A site whose schedule group is not deployed yet has nothing to reconcile when no agent is scheduled
    Given the site's schedule group is not deployed yet
    When the site deploys
    Then the deploy step says there is no schedule group yet and no agent needs one

  Scenario: A site whose schedule group is not deployed yet is refused when an agent needs it
    Given the site's schedule group is not deployed yet
    And the definition of "rate-daily" says to run at "0 6 * * *" in "America/New_York"
    When the site deploys
    Then the deploy step stops with a message that says the schedule group is not deployed yet

  Scenario: A schedule the scheduler cannot express is refused when the definition is checked
    When a definition says to run at "0 6 15 * 1" in "America/New_York"
    Then the definition is refused with a message that says a day of the month and a day of the week cannot both be named

  Scenario Outline: A cron expression becomes the scheduler's six fields
    When the cron expression "<cron>" is translated for the scheduler
    Then it becomes "<scheduler>"

    Examples:
      | cron          | scheduler               |
      | 0 6 * * *     | cron(0 6 * * ? *)       |
      | */15 * * * *  | cron(*/15 * * * ? *)    |
      | 0 9 * * 1-5   | cron(0 9 ? * 2-6 *)     |
      | 0 9 * * 0     | cron(0 9 ? * 1 *)       |
      | 0 9 * * 7     | cron(0 9 ? * 1 *)       |
      | 30 4 1 * *    | cron(30 4 1 * ? *)      |
      | 0 12 * 1,6 SAT | cron(0 12 ? 1,6 SAT *) |
      | 0 8 * * 1,3,5 | cron(0 8 ? * 2,4,6 *)   |
      | 0 8 * * 5#1   | cron(0 8 ? * 6#1 *)     |
