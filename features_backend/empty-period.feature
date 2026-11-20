Feature: An empty period sends nothing and says so
  A periodic list whose period has no qualifying item and no words a person wrote has nothing to say. By default nothing is made: no Announcement, no Delivery,
  no email. The run ends as "nothing to do" with the reason "no items reached the list's bar", and that reason is on Today beside the mark and the words, so an
  editor can see the list was woken and why it held back. A list may instead be set to make the period's draft for a person to fill: the draft has no words, it
  cannot go by itself, and it goes only when a person writes into it and the rung allows. No placeholder issue is ever made or sent. A person's own words make a
  period non-empty, whether they were written before the tick or into the draft afterwards; an agent's text never does. Nothing here sends an email: every
  Delivery is a record, and the specs read the records.

  Background:
    Given the site "mom" with its wake queue, its schedule group, its list settings and its announcement records
    And the agent "announce-lists" runs the procedure "announce_list", is switched on and is linked to the router publication of the site
    And "ryan" is an admin and "ellie" is an editor
    And the site's agent policy has the lists at the rung "prepare"

  Scenario: No qualifying item sends nothing and records why
    Given the weekly list "weekly" is sent on "monday" at "04:00" in "America/New_York"
    And these Stories are in the period
      | story    | stars | section | reviewed |
      | two-star | 2     | science | yes      |
    When the scheduler fires the entry for the list "weekly" for the time "2026-11-16T09:00:00Z"
    And the runner handles the next scheduled message
    Then the catalog holds no Announcement
    And no email was sent
    And the run says "no items reached the list's bar"
    And the run tells the runner it found nothing to do because "no_items_reached_bar"

  Scenario: Today shows the reason
    Given the weekly list "weekly" is sent on "monday" at "04:00" in "America/New_York"
    And these Stories are in the period
      | story    | stars | section | reviewed |
      | two-star | 2     | science | yes      |
    When the scheduler fires the entry for the list "weekly" for the time "2026-11-16T09:00:00Z"
    And the runner handles the next scheduled message
    Then Today for "2026-11-16" in "America/New_York" shows the run of "2026-11-16T09:00:00Z" as "– Nothing to do 1" with the reason "1 no_items_reached_bar"

  Scenario: A period that has an issue is a run that did its work
    Given the weekly list "weekly" is sent on "monday" at "04:00" in "America/New_York"
    And these Stories are in the period
      | story      | stars | section | reviewed |
      | slow-water | 4     | science | yes      |
    When the scheduler fires the entry for the list "weekly" for the time "2026-11-16T09:00:00Z"
    And the runner handles the next scheduled message
    Then the run tells the runner it did its work

  Scenario: A tick that finds its period already decided has nothing more to do
    Given the weekly list "weekly" is sent on "monday" at "04:00" in "America/New_York"
    And these Stories are in the period
      | story      | stars | section | reviewed |
      | slow-water | 4     | science | yes      |
    When the scheduler fires the entry for the list "weekly" for the time "2026-11-16T09:00:00Z"
    And the scheduler fires the entry for the list "weekly" for the time "2026-11-18T09:00:00Z"
    And the runner handles every scheduled message
    Then the run says "already decided for this period"
    And the run tells the runner it found nothing to do because "already_decided"

  Scenario: A list set to draft_only makes the draft and sends nothing by itself
    Given the weekly list "weekly" is sent on "monday" at "04:00" in "America/New_York" and its empty period is "draft_only"
    And these Stories are in the period
      | story    | stars | section | reviewed |
      | two-star | 2     | science | yes      |
    When the scheduler fires the entry for the list "weekly" for the time "2026-11-16T09:00:00Z"
    And the runner handles the next scheduled message
    And the due Announcements are released at "2026-11-16T09:00:00Z"
    Then the Announcement "roundup:weekly:2026-W47" is about no Story
    And the email of the Announcement "roundup:weekly:2026-W47" is a draft with no words
    And the run says "no items reached the list's bar; a draft waits for a person to write it"
    And the Delivery of the list "weekly" may not go at "2026-11-16T09:30:00Z" because "the words are not ready"
    And opening an attempt for the Delivery of the list "weekly" at "2026-11-16T09:30:00Z" is refused because "the words are not ready"
    And no email was sent

  Scenario: A draft_only list with items makes its issue as any list does
    Given the weekly list "weekly" is sent on "monday" at "04:00" in "America/New_York" and its empty period is "draft_only"
    And these Stories are in the period
      | story      | stars | section | reviewed |
      | slow-water | 4     | science | yes      |
    When the scheduler fires the entry for the list "weekly" for the time "2026-11-16T09:00:00Z"
    And the runner handles the next scheduled message
    Then the Announcement "roundup:weekly:2026-W47" is about the Stories "slow-water" and no others
    And the email of the Announcement "roundup:weekly:2026-W47" is ready with the words "For weekly: slow-water"

  Scenario: A person's note makes the draft sendable, and the rung decides whether it waits for approval
    Given the weekly list "weekly" is sent on "monday" at "04:00" in "America/New_York" and its empty period is "draft_only"
    And these Stories are in the period
      | story    | stars | section | reviewed |
      | two-star | 2     | science | yes      |
    When the scheduler fires the entry for the list "weekly" for the time "2026-11-16T09:00:00Z"
    And the runner handles the next scheduled message
    And ellie writes "Back next week." into the draft of the list "weekly" for the period of "2026-11-16T09:00:00Z"
    Then the email of the Announcement "roundup:weekly:2026-W47" is ready with the words "For weekly: ellie wrote: Back next week."
    And the Delivery of the list "weekly" may not go at "2026-11-16T10:00:00Z" because "waiting for approval"
    When the Delivery of the list "weekly" is approved and sent at "2026-11-16T10:05:00Z"
    Then the Announcement "roundup:weekly:2026-W47" is not cancelled

  Scenario: At the rung that publishes by policy, a person's note is enough
    Given the site's agent policy has the lists at the rung "publish_auto"
    And the weekly list "weekly" is sent on "monday" at "04:00" in "America/New_York" and its empty period is "draft_only"
    And these Stories are in the period
      | story    | stars | section | reviewed |
      | two-star | 2     | science | yes      |
    When the scheduler fires the entry for the list "weekly" for the time "2026-11-16T09:00:00Z"
    And the runner handles the next scheduled message
    And ellie writes "Back next week." into the draft of the list "weekly" for the period of "2026-11-16T09:00:00Z"
    Then the Delivery of the list "weekly" may go at "2026-11-16T10:00:00Z"

  Scenario: An agent's text does not make the period an issue
    Given the weekly list "weekly" is sent on "monday" at "04:00" in "America/New_York" and its empty period is "draft_only"
    And these Stories are in the period
      | story    | stars | section | reviewed |
      | two-star | 2     | science | yes      |
    When the scheduler fires the entry for the list "weekly" for the time "2026-11-16T09:00:00Z"
    And the runner handles the next scheduled message
    And an agent writes "Nothing to report." into the draft of the list "weekly" for the period of "2026-11-16T09:00:00Z"
    Then the run is refused with "Only a person's own words make an empty period an issue"
    And the email of the Announcement "roundup:weekly:2026-W47" is a draft with no words

  Scenario: A person cannot write into a period that has no draft
    Given the weekly list "weekly" is sent on "monday" at "04:00" in "America/New_York"
    When ellie writes "Back next week." into the draft of the list "weekly" for the period of "2026-11-16T09:00:00Z"
    Then the run is refused with "There is no open issue roundup:weekly:2026-W47 to write into"
    And the catalog holds no Announcement

  Scenario: A person's note written before the tick makes the period an issue
    Given the weekly list "weekly" is sent on "monday" at "04:00" in "America/New_York"
    And these Stories are in the period
      | story    | stars | section | reviewed |
      | two-star | 2     | science | yes      |
    And a person ellie wrote the note "Back next week." for the period at "2026-11-14T15:00:00Z"
    When the scheduler fires the entry for the list "weekly" for the time "2026-11-16T09:00:00Z"
    And the runner handles the next scheduled message
    Then the Announcement "roundup:weekly:2026-W47" is about no Story
    And the email of the Announcement "roundup:weekly:2026-W47" is ready with the words "For weekly: ellie wrote: Back next week."
    And the run tells the runner it did its work
    And no email was sent

  Scenario: Below prepare a draft_only list makes no draft
    Given the weekly list "weekly" is sent on "monday" at "04:00" in "America/New_York" with its own rung "observe" and its empty period is "draft_only"
    And these Stories are in the period
      | story    | stars | section | reviewed |
      | two-star | 2     | science | yes      |
    When the scheduler fires the entry for the list "weekly" for the time "2026-11-16T09:00:00Z"
    And the runner handles the next scheduled message
    Then the catalog holds no Announcement
    And the run says "the rung is below prepare, so nothing is made"

  Scenario: An empty draft is cancelled when the next period has an issue
    Given the weekly list "weekly" is sent on "monday" at "04:00" in "America/New_York" and its empty period is "draft_only"
    And these Stories are in the period
      | story      | stars | section | reviewed | qualified            |
      | slow-water | 4     | science | yes      | 2026-11-20T15:00:00Z |
    When the scheduler fires the entry for the list "weekly" for the time "2026-11-16T09:00:00Z"
    And the runner handles the next scheduled message
    And the scheduler fires the entry for the list "weekly" for the time "2026-11-23T09:00:00Z"
    And the runner handles the next scheduled message
    Then the Announcement "roundup:weekly:2026-W47" is cancelled because "not released before the next period; items carried forward"
    And the Announcement "roundup:weekly:2026-W48" is about the Stories "slow-water" and no others
    And no email was sent

  Scenario: The empty period setting is a named choice for a periodic list
    When ryan saves a list with a weekly cadence and the empty period "placeholder"
    Then the list settings are refused with "emptyPeriod must be one of: nothing, draft_only"
    When ryan saves a list with an every-item cadence and the empty period "draft_only"
    Then the list settings are refused with "has no period, so it names no emptyPeriod"
    When ryan saves the list "weekly" as a weekly list sent on "monday" at "04:00" in "America/New_York" run by "announce-lists" because "Monday morning issue"
    Then the list "weekly" sends nothing in an empty period
