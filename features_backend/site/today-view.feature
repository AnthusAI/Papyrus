Feature: Today says what the system did, what it decided to do nothing about, and what it cost
  An editor opens one page, or runs `papyrus today`, and answers "what did the system do today?" without opening any run.
  Today lists each responsibility's runs for one day, counted by what came of them: did it, nothing to do, asked, failed, outcome
  unknown. Every outcome is shown as a mark and its words, never a colour alone. A run that decided there was nothing to do is
  counted with its reason, because that is how an editor sees an agent is alive and why it held back. An agent that started
  nothing is listed as one that did not run, with why. The cost of a responsibility is the sum of its runs' costs, and a run that
  recorded no cost is counted as unknown rather than as free. Today only reads: it reads the day's runs by the run status index
  with a time range, and the agents through the tenant index, and never lists a whole table.

  Background:
    Given a site whose day is Monday 16 November 2026 in New York
    And the site has the agents "Weekly digest" (disabled), "Announce releases" (enabled, nothing woke it) and "Rate new references" (enabled)

  Scenario: A day with runs shows counts per responsibility and outcome
    Given the "rate" responsibility finished 6 runs that did the work, 1 that found nothing to do and 1 that asked a person
    And the "translate" responsibility finished 3 runs that did the work
    When Today is read for the day
    Then the "Rate and curate" line says "✓ Did it 6, – Nothing to do 1, ? Asked 1"
    And the "Translate" line says "✓ Did it 3"
    And the day's total is 11 runs

  Scenario: A run that found nothing to do shows its reason
    Given the "announce" responsibility finished 2 runs that found nothing to do because "not_rated" and 1 because "under_channel_bar"
    When Today is read for the day
    Then the "Announce" line says "– Nothing to do 3"
    And the "Announce" line gives the nothing-to-do reasons "2 not_rated, 1 under_channel_bar"
    And nothing-to-do runs are not counted as failures

  Scenario: A failed run and an outcome unknown run are counted in words with their marks
    Given the "translate" responsibility finished 1 run that failed with "timed_out" and has 1 run whose outcome is unknown
    When Today is read for the day
    Then the "Translate" line says "✗ Failed 1, ! Outcome unknown 1"
    And the "Translate" line gives the failed reasons "1 timed_out"

  Scenario: A run still going, and a run recorded before outcomes, are counted in words too
    Given the "rate" responsibility has 1 run still running and 1 finished run recorded before outcomes existed
    When Today is read for the day
    Then the "Rate and curate" line says "… Not finished yet 1, Recorded before outcomes 1"
    And every run of the day is in exactly one count

  Scenario: An agent that did not run says so and why
    When Today is read for the day
    Then "Weekly digest" is listed as "Did not run" because it is disabled
    And "Announce releases" is listed as "Did not run" because nothing woke it today
    And "Rate new references" is not listed as one that did not run once it has a run today

  Scenario: Cost is the sum of the runs, and a run with no recorded cost is not counted as free
    Given the "translate" responsibility finished 2 runs that cost 0.25 and 0.16 and 1 run that recorded no cost
    When Today is read for the day
    Then the "Translate" line says its cost is "$0.41 (cost unknown for 1 run)"
    And the day's total cost is "$0.41 (cost unknown for 1 run)"

  Scenario: A run that started before the day or after it is not counted
    Given the "rate" responsibility finished 1 run at 23:30 on Sunday and 1 at 00:30 on Tuesday, New York time
    And the "rate" responsibility finished 2 runs on Monday
    When Today is read for the day
    Then the "Rate and curate" line counts 2 runs

  Scenario: Today is read by index, never by listing a table
    Given the "rate" responsibility finished 2 runs that did the work
    When Today is read for the day
    Then each run status was read once, with a time range, from the run status index
    And no whole-table list of runs or agents was made

  Scenario: Each responsibility line points to the runs
    Given the "rate" responsibility finished 2 runs started by the automation "rate.new-references"
    When Today is read for the day
    Then the "Rate and curate" line gives the command "papyrus automations runs --id rate.new-references"

  Scenario: The command line prints the same lines
    Given the "announce" responsibility finished 2 runs that found nothing to do because "not_rated"
    When an editor runs the command "papyrus today"
    Then the printed Today has the line "Announce: – Nothing to do 2 · $0.00"
    And the printed Today has the line "– Weekly digest: Did not run. Disabled: the router starts nothing for a disabled automation."

  Scenario: Today is for editors and admins
    When a reader who is not on staff asks for Today
    Then Today is refused

  Scenario: A day that does not exist is refused in words
    When Today is read for the day "2026-13-45"
    Then Today is refused with a message that says it is not a date

  Scenario: Today on a site whose records carry a tenant lists its agents
    A dedicated site whose records carry a tenant (its build sets PAPYRUS_TENANT_ID) gives Today's function that tenant, so the agents are read
    through the Automation tenant index as the site's tenant, and Today does not answer that it is unavailable.
    Given the site is a dedicated site whose records carry the tenant "machines-on-machines", and its function is built with that tenant
    And the "rate" responsibility finished 2 runs that did the work
    When Today is read for the day through the function's own client
    Then Today is ready, not unavailable
    And the agents were read through the tenant index for "machines-on-machines"
    And "Weekly digest" is listed as "Did not run" because it is disabled
    And "Announce releases" is listed as "Did not run" because nothing woke it today
    And the "Rate and curate" line says "✓ Did it 2"
