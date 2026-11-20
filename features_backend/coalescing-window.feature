Feature: A paid step waits for quiet before it starts; a free step does not
  A burst of edits must not start ten paid runs (PPY-67e3cd, slice B5 of the always-on agents design). When a Story changes, the change feed hands each wake to
  the wake gate. A step marked free is put on the queue at once, on every change. A step marked paid does not start: the change sets or replaces ONE follow-up
  timer for that Story and that step, due when the Story has been quiet for the site's window. The window is site data in the agent policy document: one length after
  an agent's change and a shorter one after a person's own action (Ryan's ruling: 30 minutes to 24 hours, about 5 minutes after a person). A site that has set
  none starts with the shortest of the ruling. The timer's wake key leaves out the version, so ten changes are one pending wake, and the run that follows takes the
  version that is current when the timer fires. Nothing sweeps: the timer is the only thing that waits.

  Background:
    Given the site "sample" with its wake gate
    And these agents listen through the gate
      | agent         | responsibility | procedure        | paid  | change          | filter     |
      | fact-check    | fact_check     | story.fact_check | true  | version_created | type=story |
      | sources-check | sources        | story.sources    | false | version_created | type=story |
    And the owner has set the quiet window to 60 minutes after an agent and 5 minutes after a person

  Scenario: Ten saves in a minute start one fact check
    When a person writes versions 2 to 11 of the Story "story-1", 6 seconds apart from "2026-11-18T09:00:00Z"
    Then the gate queue holds 0 wakes for the agent "fact-check"
    And the site's wait timers hold exactly 1 entry
    And the pending wait for "fact-check" on "story-1" is due at "2026-11-18T09:05:54Z"
    When the clock reaches "2026-11-18T09:05:54Z"
    Then the gate queue holds 1 wake for the agent "fact-check"
    And the site's wait timers hold exactly 0 entries

  Scenario: The run uses the last version
    When a person writes versions 2 to 11 of the Story "story-1", 6 seconds apart from "2026-11-18T09:00:00Z"
    And the clock reaches "2026-11-18T09:05:54Z"
    Then the wake for "fact-check" names the Story "story-1" and no version
    And the wake for "fact-check" says in words that it waited for the quiet window
    And the run that takes it reads the current version, which is version 11

  Scenario: A person's edit shortens the wait
    When the agent "writer" writes version 2 of the Story "story-1" at "2026-11-18T09:00:00Z"
    Then the pending wait for "fact-check" on "story-1" is due at "2026-11-18T10:00:00Z"
    When a person writes version 3 of the Story "story-1" at "2026-11-18T09:10:00Z"
    Then the site's wait timers hold exactly 1 entry
    And the pending wait for "fact-check" on "story-1" is due at "2026-11-18T09:15:00Z"

  Scenario: A free step runs on each save
    When a person writes versions 2 to 11 of the Story "story-1", 6 seconds apart from "2026-11-18T09:00:00Z"
    Then the gate queue holds 10 wakes for the agent "sources-check"

  Scenario: Another Story has its own wait
    When a person writes version 2 of the Story "story-1" at "2026-11-18T09:00:00Z"
    And a person writes version 2 of the Story "story-2" at "2026-11-18T09:01:00Z"
    Then the site's wait timers hold exactly 2 entries
    When the clock reaches "2026-11-18T09:10:00Z"
    Then the gate queue holds 2 wakes for the agent "fact-check"

  Scenario: Changing the window changes only later waits
    When a person writes version 2 of the Story "story-1" at "2026-11-18T09:00:00Z"
    Then the pending wait for "fact-check" on "story-1" is due at "2026-11-18T09:05:00Z"
    When the owner has set the quiet window to 60 minutes after an agent and 20 minutes after a person
    Then the pending wait for "fact-check" on "story-1" is due at "2026-11-18T09:05:00Z"
    When a person writes version 3 of the Story "story-1" at "2026-11-18T09:01:00Z"
    Then the pending wait for "fact-check" on "story-1" is due at "2026-11-18T09:21:00Z"

  Scenario: A site that has set no window starts with the shortest of the ruling
    Given the owner has set no quiet window
    When the agent "writer" writes version 2 of the Story "story-1" at "2026-11-18T09:00:00Z"
    Then the pending wait for "fact-check" on "story-1" is due at "2026-11-18T09:30:00Z"
    When a person writes version 3 of the Story "story-1" at "2026-11-18T09:01:00Z"
    Then the pending wait for "fact-check" on "story-1" is due at "2026-11-18T09:06:00Z"

  Scenario: The owner may not set a window outside the ruling
    When the owner tries to set the quiet window to 60 seconds after an agent
    Then the policy refuses it, saying the window is from 1800 to 86400 seconds
