Feature: The newsroom suggests a time for a scheduled Story from the publication's own rhythm
  A newsroom that writes faster than it wants to publish spreads its Stories out. "Suggest a time" learns when this publication publishes from two small facts, each
  raised once, when a Story is published for the first time: how many first publications fell in each hour of the week in the publication's time zone, and the total
  with the moment of the first one. It reads nothing else about the past: no Story is read to make a suggestion. The suggestion is the earliest hour after both now and
  the latest scheduled time plus the publication's mean gap between first publications, in the hour of the following day the publication has used most. There is no fixed
  spacing and no fixed window, so a publication that publishes hourly gets hourly slots and one that publishes twice a week gets that. An editor may always pick another
  time. A publication with no history gets no suggestion, and is told why. The same read serves the console, `papyrus stories schedule-suggest` and the agents' tool.

  Background:
    Given the publication's time zone is America/New_York
    And Sam may publish on this site
    And it is 10 November 2026 at 15:00 UTC

  Scenario: A publication with no history has no suggestion yet
    Given the publication has published nothing yet
    When Sam asks for a suggested time
    Then the picker says "No suggestion yet: this publication has no publishing history."

  Scenario: The next weekday morning after the latest scheduled Story
    Given the publication first published a Story at 09:00 New York time on each weekday from 26 October to 6 November 2026
    And the Story "Robots in the warehouse" has 3 versions
    And the Story is scheduled for 11 November 2026 at 08:00 New York time
    When Sam asks for a suggested time
    Then the suggested time is "Fri 13 Nov 2026, 09:00 EST"

  Scenario: A weekend passes to Monday morning
    Given the publication first published a Story at 09:00 New York time on each weekday from 26 October to 6 November 2026
    And it is 14 November 2026 at 03:00 UTC
    When Sam asks for a suggested time
    Then the suggested time is "Mon 16 Nov 2026, 09:00 EST"

  Scenario: A first publication is counted once, in the hour it went live
    Given the Story "Robots in the warehouse" has 1 versions
    When Sam publishes version 1 now
    And the copywriting agent saved version 2 on 10 November 2026
    And Sam publishes version 2 now
    Then the publication's rhythm counts 1 first publication
    And the hour the Story went live in is the one counted

  Scenario: A site with no time zone keeps no rhythm
    Given the publication has no time zone set
    And the Story "Robots in the warehouse" has 3 versions
    When Sam publishes version 3 now
    Then the publication's rhythm counts 0 first publications

  Scenario: The command line suggests a time
    Given the publication first published a Story at 09:00 New York time on each weekday from 26 October to 6 November 2026
    And the Story "Robots in the warehouse" has 3 versions
    When an agent types "papyrus stories schedule-suggest"
    Then the output suggests "Wed 11 Nov 2026, 09:00 EST"

  Scenario: The command line says when there is nothing to suggest
    Given the publication has published nothing yet
    When an agent types "papyrus stories schedule-suggest"
    Then the output says there is no suggestion yet

  Scenario: The agents' tool is the same table
    Given the publication first published a Story at 09:00 New York time on each weekday from 26 October to 6 November 2026
    And the Story "Robots in the warehouse" has 3 versions
    When an agent asks the stories_schedule_suggest tool for a time
    Then the tool answers with the suggestion "Wed 11 Nov 2026, 09:00 EST"

  Scenario: A newer version is flagged as soon as it is saved
    Given the Story "Robots in the warehouse" has 3 versions
    And Sam scheduled version 3 for 13 November 2026 at 09:00 New York time
    And the copywriting agent saved version 4 on 10 November 2026
    When the newsroom reads the Story's schedule
    Then the schedule entry says a newer version exists and that it is still scheduled

  Scenario: An unrated Story says what scheduling will and will not do
    Given the Story "Robots in the warehouse" has 3 versions
    When Sam schedules version 3 for 13 November 2026 at 09:00 New York time
    And the newsroom reads the Story's schedule
    Then the schedule entry carries the note "Unrated: it will publish but will not be listed or announced until it is rated."
