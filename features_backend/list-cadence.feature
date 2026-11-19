Feature: A list carries its cadence, time, time zone and rule as data
  Every subscription list (a Caducus public-audience list) has settings in the site's data: its cadence (every item, daily or weekly), the local time and
  time zone of a periodic one, its rule (sections, types, tags and a minimum star rating that is never under three), whether the source must have been
  reviewed, its working document (an issue Story or the Delivery alone), its template, the agent that runs it and, optionally, its own rung. The settings are a
  versioned site document that only an admin who is a person changes; each change has a reason.

  A periodic list is a scheduled wake. The schedule reconciler, which runs when the site deploys and whenever a person runs the schedules command, makes one
  entry in the site's schedule group for each periodic list, from the list's settings, in the list's own local time and zone. A list that is added, moved or
  removed needs no definition file and no code: only that reconcile. An every-item list has no clock; it is woken when a Story's page goes live or its rating
  changes. Every cadence ends the same way: one Announcement, decided once, and one email Delivery whose audience is the list, drafted at the rung that applies.
  A list's own rung can only narrow what the site's policy allows. An empty period makes nothing.

  Background:
    Given the site "mom" with its wake queue, its schedule group, its list settings and its announcement records
    And the agent "announce-lists" runs the procedure "announce_list", is switched on and is linked to the router publication of the site
    And "ryan" is an admin and "ellie" is an editor
    And the site's agent policy has the lists at the rung "prepare"

  Scenario: A new weekly list needs no code and no deploy beyond the reconcile
    When ryan saves the list "weekly" as a weekly list sent on "monday" at "04:00" in "America/New_York" run by "announce-lists" because "Monday morning issue"
    And the schedules are reconciled
    Then the list settings are at version 1, saved by "ryan" with the reason "Monday morning issue"
    And the schedule group holds exactly 1 entry
    And the entry for the list "weekly" says "cron(0 4 ? * 2 *)" in the time zone "America/New_York"
    And the entry for the list "weekly" wakes "announce-lists" with the list "weekly" and no offset from UTC in its time

  Scenario: A weekly list wakes at its local time and makes its issue
    Given the weekly list "weekly" is sent on "monday" at "04:00" in "America/New_York"
    And these Stories are in the period
      | story        | stars | section  | reviewed |
      | slow-water   | 4     | science  | yes      |
      | quiet-engine | 3     | science  | no       |
    When the scheduler fires the entry for the list "weekly" for the time "2026-11-16T09:00:00Z"
    Then the wake queue holds 1 scheduled message
    And the message's wake key is "announce-lists:list:weekly|schedule|2026-11-16T09:00:00Z"
    And the message says in words that it is for the list "weekly"
    When the runner handles the next scheduled message
    Then the Announcement "roundup:weekly:2026-W47" is planned for "2026-11-16T09:00:00Z"
    And that Announcement is about the Stories "slow-water" and "quiet-engine"
    And that Announcement has one email Delivery for the list "weekly"

  Scenario: The issue's edit window gives it its lock time and keeps its scheduled release
    Given the weekly list "weekly" is sent on "monday" at "04:00" in "America/New_York"
    And the announcement settings give a roundup issue on the email channel a window of 7200 minutes with a lock lead of 120 minutes
    And these Stories are in the period
      | story      | stars | section | reviewed |
      | slow-water | 4     | science | yes      |
    When the scheduler fires the entry for the list "weekly" for the time "2026-11-16T09:00:00Z"
    And the runner handles the next scheduled message
    Then the Announcement "roundup:weekly:2026-W47" is planned for "2026-11-16T09:00:00Z"
    And that Announcement's email Delivery goes at "2026-11-16T09:00:00Z" and locks at "2026-11-16T07:00:00Z"

  Scenario: A daily list wakes every day and a tick that is delivered twice is one decision
    Given the daily list "daily" is sent at "06:00" in "America/New_York"
    And these Stories are in the period
      | story      | stars | section | reviewed |
      | slow-water | 3     | science | yes      |
    When the scheduler fires the entry for the list "daily" for the time "2026-11-16T11:00:00Z"
    And the scheduler fires the entry for the list "daily" for the time "2026-11-16T11:00:00Z" again
    And the scheduler fires the entry for the list "daily" for the time "2026-11-17T11:00:00Z"
    And the runner handles every scheduled message
    Then the catalog holds the Announcements "roundup:daily:2026-11-16" and "roundup:daily:2026-11-17" and no others
    And the entry for the list "daily" says "cron(0 6 * * ? *)" in the time zone "America/New_York"

  Scenario: An every-item list reacts to a publish and has no clock
    Given the every-item list "new-stories" with a minimum of 4 stars
    When the schedules are reconciled
    Then the schedule group holds exactly 0 entries
    When the Story "agents-that-lie" goes live at 4 stars in the section "science"
    Then the Announcement "story-published:agents-that-lie" is planned for "2026-11-16T14:00:00Z"
    And that Announcement has one email Delivery for the list "new-stories"
    When the Story "agents-that-lie" is republished
    Then the catalog holds the Announcements "story-published:agents-that-lie" and no others

  Scenario: An every-item list does not carry a Story under its bar
    Given the every-item list "new-stories" with a minimum of 4 stars
    When the Story "plain-note" goes live at 3 stars in the section "science"
    Then the catalog holds no Announcement
    And the run says "no every-item list carries this Story at a rung that writes"

  Scenario: One Story that two every-item lists carry is one message
    Given the every-item list "new-stories" with a minimum of 3 stars
    And the every-item list "science-only" with a minimum of 3 stars for the section "science"
    When the Story "slow-water" goes live at 4 stars in the section "science"
    Then the catalog holds the Announcements "story-published:slow-water" and no others
    And that Announcement has one email Delivery for the lists "new-stories" and "science-only"

  Scenario: A rule under three stars is refused
    When ryan saves the list "bad" as a weekly list with a minimum of 2 stars
    Then the list settings are refused with "A list cannot carry anything under 3 stars"
    And the list settings are at version 0
    Given the weekly list "weekly" is sent on "monday" at "04:00" in "America/New_York"
    When ryan changes the minimum rating of the list "weekly" to 2
    Then the list settings are refused with "A list cannot carry anything under 3 stars"
    And the list "weekly" still has a minimum of 3 stars

  Scenario: A document edited by hand under the floor is not read, so nothing is made
    Given the weekly list "weekly" is sent on "monday" at "04:00" in "America/New_York"
    And the stored settings of the list "weekly" are edited by hand to a minimum of 1 star
    And these Stories are in the period
      | story       | stars | section | reviewed |
      | unrated-one | 0     | science | yes      |
      | two-star    | 2     | science | yes      |
    When the scheduler fires the entry for the list "weekly" for the time "2026-11-16T09:00:00Z"
    And the runner handles the next scheduled message
    Then the run is refused with "A list cannot carry anything under 3 stars"
    And the catalog holds no Announcement

  Scenario: Changing the time changes the next send only
    Given the weekly list "weekly" is sent on "monday" at "04:00" in "America/New_York"
    And these Stories are in the period
      | story      | stars | section | reviewed |
      | slow-water | 4     | science | yes      |
    When the scheduler fires the entry for the list "weekly" for the time "2026-11-16T09:00:00Z"
    And the runner handles the next scheduled message
    And ryan changes the time of the list "weekly" to "tuesday" at "05:30" because "Readers asked for Tuesdays"
    And the schedules are reconciled
    Then the entry for the list "weekly" says "cron(30 5 ? * 3 *)" in the time zone "America/New_York"
    And the schedule group holds exactly 1 entry
    And the Announcement "roundup:weekly:2026-W47" is still planned for "2026-11-16T09:00:00Z"
    When the scheduler fires the entry for the list "weekly" for the time "2026-11-17T10:30:00Z"
    And the runner handles the next scheduled message
    Then the catalog holds the Announcements "roundup:weekly:2026-W47" and no others
    When the scheduler fires the entry for the list "weekly" for the time "2026-11-24T10:30:00Z"
    And the runner handles the next scheduled message
    Then the Announcement "roundup:weekly:2026-W48" is planned for "2026-11-24T10:30:00Z"

  Scenario: Every cadence makes the same kind of Announcement and Delivery
    Given the weekly list "weekly" is sent on "monday" at "04:00" in "America/New_York"
    And the daily list "daily" is sent at "06:00" in "America/New_York"
    And the every-item list "new-stories" with a minimum of 3 stars
    And these Stories are in the period
      | story      | stars | section | reviewed |
      | slow-water | 4     | science | yes      |
    When the scheduler fires the entry for the list "weekly" for the time "2026-11-16T09:00:00Z"
    And the scheduler fires the entry for the list "daily" for the time "2026-11-16T11:00:00Z"
    And the runner handles every scheduled message
    And the Story "slow-water" goes live at 4 stars in the section "science"
    Then the catalog holds 3 Announcements and 3 Deliveries
    And each Delivery is an email Delivery on the sending account "mom-sending" for exactly one list, drafted and ready, with its words in a file
    And every Delivery has the same fields as the others
    And every Announcement has the fields of the others, differing only in key, kind and trigger

  Scenario: An empty period sends nothing and says so
    Given the weekly list "weekly" is sent on "monday" at "04:00" in "America/New_York"
    And these Stories are in the period
      | story    | stars | section | reviewed |
      | two-star | 2     | science | yes      |
    When the scheduler fires the entry for the list "weekly" for the time "2026-11-16T09:00:00Z"
    And the runner handles the next scheduled message
    Then the catalog holds no Announcement
    And the run says "no items reached the list's bar"

  Scenario: A list that requires a reviewed source leaves out a Story nobody reviewed
    Given the weekly list "weekly" is sent on "monday" at "04:00" in "America/New_York" and requires a reviewed source
    And these Stories are in the period
      | story        | stars | section | reviewed |
      | slow-water   | 4     | science | yes      |
      | quiet-engine | 4     | science | no       |
    When the scheduler fires the entry for the list "weekly" for the time "2026-11-16T09:00:00Z"
    And the runner handles the next scheduled message
    Then that Announcement is about the Stories "slow-water" and no others

  Scenario Outline: The list's rung and the site's policy: the lower one decides
    Given the weekly list "weekly" is sent on "monday" at "04:00" in "America/New_York" with its own rung "<own>"
    And the site's agent policy has the lists at the rung "<policy>"
    And these Stories are in the period
      | story      | stars | section | reviewed |
      | slow-water | 4     | science | yes      |
    When the scheduler fires the entry for the list "weekly" for the time "2026-11-16T09:00:00Z"
    And the runner handles the next scheduled message
    Then the Delivery of the list "weekly" needs "<approval>" approval, decided by "<rung>"

    Examples:
      | own          | policy       | approval | rung         |
      | publish_auto | prepare      | hard     | prepare      |
      | publish_soft | publish_auto | soft     | publish_soft |
      | -            | publish_soft | soft     | publish_soft |
      | -            | publish_auto | none     | publish_auto |

  Scenario Outline: Below prepare nothing is made
    Given the weekly list "weekly" is sent on "monday" at "04:00" in "America/New_York" with its own rung "<own>"
    And these Stories are in the period
      | story      | stars | section | reviewed |
      | slow-water | 4     | science | yes      |
    When the scheduler fires the entry for the list "weekly" for the time "2026-11-16T09:00:00Z"
    And the runner handles the next scheduled message
    Then the catalog holds no Announcement
    And the run says "the rung is below prepare, so nothing is made"

    Examples:
      | own     |
      | off     |
      | observe |
      | propose |
      | draft   |

  Scenario: Only an admin who is a person changes a list
    When ellie saves the list "weekly" as a weekly list sent on "monday" at "04:00" in "America/New_York" run by "announce-lists" because "I would like one"
    Then the list settings are refused with "Only an admin changes a list's settings."
    When an agent saves the list "weekly" as a weekly list sent on "monday" at "04:00" in "America/New_York" run by "announce-lists" because "I would like one"
    Then the list settings are refused with "An agent may never change a list's settings"
    And the list settings are at version 0

  Scenario Outline: A list's settings must say what they mean
    When ryan saves a list with <fault>
    Then the list settings are refused with "<message>"

    Examples:
      | fault                                       | message                                            |
      | a weekly cadence and no weekday             | sendAt.day must be a weekday name                  |
      | an every-item cadence and a send time       | is an every-item list, so it names no sendAt       |
      | a daily cadence and the working document story | only a weekly issue has an archive page         |
      | a daily cadence and the time zone "Mars/Olympus" | timeZone must be a time zone name              |
      | a daily cadence and the time "25:00"        | time must be a local time of day                   |
      | a cadence of "hourly"                       | cadence must be one of: each, daily, weekly        |

  Scenario: A list whose agent is switched off is refused, naming the list
    Given the weekly list "weekly" is sent on "monday" at "04:00" in "America/New_York"
    When the agent "announce-lists" is switched off
    And the schedules are reconciled
    Then the deploy step stops with a message that says the list "weekly" names the agent "announce-lists", which is switched off
    And the scheduler was asked to create, update or delete nothing more

  Scenario: A list whose agent does not exist is refused, naming the list
    When ryan saves the list "weekly" as a weekly list sent on "monday" at "04:00" in "America/New_York" run by "no-such-agent" because "A typo"
    And the schedules are reconciled
    Then the deploy step stops with a message that says the list "weekly" names the agent "no-such-agent", which is not an agent of this site

  Scenario: Removing a list removes its entry, and another helper's entry is left alone
    Given the weekly list "weekly" is sent on "monday" at "04:00" in "America/New_York"
    And a one-shot entry "due-story-17" of another helper is in the schedule group
    And the schedules are reconciled
    When ryan removes the list "weekly" because "No longer sent"
    And the schedules are reconciled
    Then the schedule group holds the one-shot entry "due-story-17" and no entry for the list "weekly"

  Scenario: Reconciling again with nothing changed writes nothing
    Given the weekly list "weekly" is sent on "monday" at "04:00" in "America/New_York"
    And the schedules are reconciled
    When the schedules are reconciled
    Then the scheduler was asked to create, update or delete nothing more

  Scenario: A wake for a list that is not there makes nothing
    Given the weekly list "weekly" is sent on "monday" at "04:00" in "America/New_York"
    And the scheduler fires the entry for the list "weekly" for the time "2026-11-16T09:00:00Z"
    And ryan removes the list "weekly" because "No longer sent"
    When the runner handles the next scheduled message
    Then the run is refused with "is not a list of this site"
    And the catalog holds no Announcement
