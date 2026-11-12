@brand-agnostic @story-schedule
Feature: Editors see and change when a Story goes live, and see the whole schedule on one page
  A newsroom that writes faster than it wants to publish picks a time for each Story and needs to see, at a glance, what is going out when. A scheduled Story
  says so on its board card and in its drawer, in an icon and in words, in the publication's own time zone, so the page reads without colour. The drawer has a
  date and time picker in that zone to set, change or clear the time, beside the existing Published state and Publish button, which do not change. A change
  shows at once and goes back to what was saved if the backend refuses it, and what the editor typed stays in the form. A time that does not exist on a
  spring-forward night is refused in plain words and a time that happens twice asks which one. A Schedule page shows the same Stories by day, week or month, in
  the publication's zone, with a plain list under the calendar and a list instead of the week grid on a phone. It reads only the time range on screen, from the
  schedule index. These scenarios use the local preview data (clearly fake Stories and people) and a fixed clock in an isolated browser at 375 and 1440 pixels,
  in light and dark, and never touch production.

  Scenario: Every state is an icon and words on the board card
    Given the Stories board with a scheduled Story, an overdue Story, a superseded Story and an unscheduled Story
    When the editor looks at the cards
    Then the scheduled card shows a calendar-clock icon and "Scheduled: Fri 13 Nov, 9:00 AM ET", the time in New York
    And the overdue card shows a warning icon and "Overdue"
    And the superseded card shows a slashed-circle icon and "Superseded: a newer version was saved"
    And the unscheduled card shows no schedule line

  Scenario: The drawer says when the Story goes live, and in the editor's own zone when that differs
    Given the Stories board with a scheduled Story
    When the editor opens the Story, in New York and then from London
    Then the drawer says "Scheduled for Fri 13 Nov 2026, 9:00 AM ET (New York), by Preview editor"
    And from London a small line adds "2:00 PM GMT your time"
    And the Publish button and the Draft state are as they were

  Scenario: An editor sets, changes and clears a time
    Given the Stories board with an unscheduled Story open in its drawer
    When the editor picks 20 November at 07:30, changes it to 21 November at 14:00, and then clears it
    Then each change shows in the drawer and on the card, and clearing takes both back
    And the backend was asked only to schedule, with the UTC instant and never a draft save, a publish or a stage move

  Scenario: A schedule the backend refuses goes back, and what was typed stays
    Given the Stories board with a scheduled Story open in its drawer
    When the editor picks a new time while the save fails, and then saves again once it works
    Then the drawer says the schedule could not be saved, shows the saved time again and keeps the typed date and time
    And a time that has already passed is refused before anything is sent

  Scenario: A time that does not exist is refused, and a time that happens twice asks which
    Given the Stories board with an unscheduled Story open in its drawer
    When the editor picks 02:30 on the night clocks go forward, and then 01:30 on the night they go back
    Then the first is refused with "That time does not exist on 14 March in New York. Pick another time." and nothing is sent
    And the second lists "01:30 EDT" and "01:30 EST", sends nothing until one is chosen, and then schedules the one chosen

  Scenario: The Schedule page shows the week in the publication's zone
    Given the Schedule page with three Stories this week and one the week after
    When the editor opens it
    Then the current week is shown in New York time with each Story's time, state in words, icon and title
    And a plain list of the same Stories follows the calendar
    And choosing Month shows all four and choosing Day shows an empty day with "Nothing is scheduled today."
    And only one week of the schedule index is read at a time, and an empty week says "Nothing is scheduled this week." and offers "Schedule a Story"

  Scenario: Events and the list work from the keyboard
    Given the Schedule page with three Stories this week
    When the editor tabs through the page
    Then every event is a focusable button, the list has a link for each Story, and Enter on an event opens its Story

  Scenario: On a phone the week is a list
    Given the Schedule page on a screen 375 pixels wide
    Then the week is shown as a list by day with the same three Stories and nothing scrolls sideways
    And the badge and the drawer's schedule row fit the phone, with targets at least 36 pixels tall

  Scenario: Flat fills, no outlines
    Given the Schedule page, the board and an open drawer in light and dark
    Then no element of the badge, the schedule row or the calendar draws a visible outline
