Feature: The command line and the agents' tools schedule Stories and read the schedule
  Agents and people at a terminal do everything an editor does in the newsroom. `papyrus stories schedule` and `stories schedule-list`, and the MCP tools
  stories_schedule and stories_schedule_list, are one operation table that the newsroom's own mutation runs, so they refuse and answer in the same words.

  Background:
    Given the publication's time zone is America/New_York
    And Sam may publish on this site
    And it is 10 November 2026 at 15:00 UTC
    And the Story "Robots in the warehouse" has 3 versions

  Scenario: Scheduling from the command line
    When an agent types "papyrus stories schedule --story LINEAGE --at '2026-11-13 09:00'"
    Then the output says the Story is scheduled for "Fri 13 Nov 2026, 09:00 EST" by Sam
    And version 3 carries the schedule: scheduled for 13 November 2026 at 14:00 UTC by Sam

  Scenario: A dry run checks and writes nothing
    When an agent types "papyrus stories schedule --story LINEAGE --at '2026-11-13 09:00' --dry-run"
    Then the output says it would schedule the Story
    And nothing is scheduled

  Scenario: Clearing a schedule from the command line
    Given Sam scheduled version 3 for 13 November 2026 at 09:00 New York time
    When an agent types "papyrus stories schedule --story LINEAGE --clear"
    Then the output says the schedule was cleared
    And the schedule is removed and will not fire

  Scenario: The command line refuses in the newsroom's words
    When an agent types "papyrus stories schedule --story LINEAGE --at '2026-03-08 02:30'"
    Then the schedule command fails with "That time does not exist on 8 March in New York. Pick another time."

  Scenario: Stories show says when the Story is scheduled
    Given Sam scheduled version 3 for 13 November 2026 at 09:00 New York time
    When an agent types "papyrus stories show --story LINEAGE"
    Then the output has a schedule line: scheduled, version 3, "2026-11-13T14:00:00Z", by Sam

  Scenario: Stories show says when a schedule is blocked by a newer version
    Given Sam scheduled version 3 for 13 November 2026 at 09:00 New York time
    And the copywriting agent saved version 4 on 12 November 2026
    And the timer delivered its event at 13 November 2026 at 14:00 UTC
    When an agent types "papyrus stories show --story LINEAGE"
    Then the output has a schedule line: blocked, version 3, "A newer version was saved after this was scheduled. Schedule it again."

  Scenario: Listing the schedule of a week
    Given Sam scheduled version 3 for 13 November 2026 at 09:00 New York time
    When an agent types "papyrus stories schedule-list --from '2026-11-09 00:00' --to '2026-11-15 23:59'"
    Then the list has one line: "Robots in the warehouse", version 3, scheduled, "Fri 13 Nov 2026, 09:00 EST", by Sam
    And the schedule was read from the schedule index, one query for each state

  Scenario: The agents' tools are the same table
    When an agent asks the stories_schedule tool to schedule the Story for "2026-11-13 09:00"
    Then version 3 carries the schedule: scheduled for 13 November 2026 at 14:00 UTC by Sam
    And the stories_schedule_list tool lists it as scheduled
