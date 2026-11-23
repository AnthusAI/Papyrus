Feature: Today puts first what only a person can move, then what is due today in the site's time zone
  The top of Today is the list of things that wait for a person and for nothing else. Under Waiting for you are the open questions: every hard gate,
  which never proceeds without an answer, and every soft review, such as the review of an announcement's draft or the day's rating review. Under
  Needs attention are the runs whose outcome is unknown, the failures nobody has acknowledged yet, the records that are Overdue and the open flags.
  Each item has its one action beside it: Answer a question, Settle a run whose outcome is unknown, Acknowledge a failure, Wake now an overdue
  record, Open a flag. Acknowledging or settling takes the run off the list and records who did it; the run stays in the history.

  Then comes Due today: every time in the site's day that something happens unless someone acts, a Delivery's lock and release, a Story scheduled
  to publish, an agent's scheduled wake, a soft review's deadline. The day and its times are in the site's own time zone, the one its publication
  names, so an editor in the newsroom reads the times the site keeps. Every read is an index: the open review requests, the runs that need a
  person, the Deliveries due and the Stories scheduled to publish; no whole table is listed.

  Background:
    Given a site in New York whose day is Monday 16 November 2026, and it is noon there

  Scenario: A hard gate shows under Waiting for you with its Answer action
    Given an open hard gate "Publish 'Agents that lie'?" about the story "agents-that-lie"
    When Today is read
    Then Waiting for you lists "Publish 'Agents that lie'?" as a hard gate with the action "Answer"
    And the Answer action opens the request "Publish 'Agents that lie'?" in the Notification Center

  Scenario: The announcement draft's review and the day's rating review wait for a person, each with its action
    Given an open hard gate "Publish 'Agents that lie'?" about the story "agents-that-lie"
    And an open soft review "X announcement draft for 'Agents that lie'" about the delivery "announcement-1#x#site#g1" that goes on without review at 15:30 New York time
    And the day's rating review "3 ratings suggested, 1 five-star candidate" is open
    When Today is read
    Then Waiting for you lists, in order, "Publish 'Agents that lie'?", "X announcement draft for 'Agents that lie'" and "3 ratings suggested, 1 five-star candidate"
    And Waiting for you lists "X announcement draft for 'Agents that lie'" as a soft review with the action "Answer"
    And Waiting for you lists "3 ratings suggested, 1 five-star candidate" as a soft review with the action "Answer"
    And the soft review "X announcement draft for 'Agents that lie'" says it goes on without review at "3:30 PM"

  Scenario: An overdue Delivery shows as Overdue, once, with its due time in local time
    Given a Delivery for x "machines" that was due to go out at 06:00 New York time and nothing ran
    And the overdue check has raised its flag
    When Today is read
    Then Needs attention lists the Delivery as "Overdue" with the action "Wake now"
    And the Overdue Delivery was due at "6:00 AM"
    And the overdue check's flag is not listed a second time
    And the Delivery's past release is not listed under Due today

  Scenario: A run whose outcome is unknown shows with a Settle action
    Given a "translate" run that was interrupted and recorded the outcome unknown
    When Today is read
    Then Needs attention lists the run as "! Outcome unknown" with the action "Settle"

  Scenario: Acknowledging clears a failure
    Given a "translate" run that failed with "timed_out" and nobody has acknowledged it
    And Today lists the failed run under Needs attention with the action "Acknowledge"
    When an editor acknowledges the failed run from Today
    And Today is read
    Then Needs attention does not list the failed run
    And the run records that the editor acknowledged it
    And the failed run stays in the history, still failed

  Scenario: Settling a run whose outcome is unknown takes it off the list and keeps the outcome
    Given a "translate" run that was interrupted and recorded the outcome unknown
    When an editor settles the run from Today
    And Today is read
    Then Needs attention does not list the run
    And the settled run stays in the history as outcome unknown

  Scenario: A reader who is not on staff cannot acknowledge a run
    Given a "translate" run that failed with "timed_out" and nobody has acknowledged it
    When a reader who is not on staff acknowledges the failed run
    Then the acknowledgement is refused
    And the failed run still needs a person

  Scenario: Due items are in the site's local time
    Given a Delivery for x "machines" that locks at 15:30 and goes out at 16:00 New York time, not yet approved
    And the story "eternal-october" is scheduled to publish at 14:00 New York time
    And the agent "Daily summary" wakes on the schedule "0 6 * * *" in "America/New_York"
    And a Delivery for x "machines" that goes out tomorrow at 09:00 New York time
    When Today is read without naming a time zone
    Then the day is Monday 16 November 2026 in "America/New_York", the site's own time zone
    And Due today lists, in order, "6:00 AM Scheduled wake: Daily summary", "2:00 PM Publishes: Eternal October", "3:30 PM Locks: x machines" and "4:00 PM Goes out: x machines"
    And the lock says it is not yet approved
    And Due today does not list the Delivery that goes out tomorrow

  Scenario: A site that names no time zone shows its times in UTC and says so
    Given the site names no time zone
    And the story "eternal-october" is scheduled to publish at 14:00 New York time
    When Today is read without naming a time zone
    Then the day is in "UTC" and Today says the site names no time zone
    And Due today lists "7:00 PM Publishes: Eternal October"

  Scenario: The command line prints what only a person can move first
    Given an open hard gate "Publish 'Agents that lie'?" about the story "agents-that-lie"
    And a "translate" run that was interrupted and recorded the outcome unknown
    When an editor runs "papyrus today"
    Then the printed Today shows Waiting for you, then Needs attention, then Due today, then what ran
    And the printed Today has a line with "? Hard gate: nothing proceeds without an answer: Publish 'Agents that lie'? (story agents-that-lie)" and "[Answer: papyrus reviews answer"
    And the printed Today has a line with "! Outcome unknown (interrupted): Translate" and "[Settle: papyrus automations acknowledge --run"

  Scenario: Today's top is read by index
    Given an open hard gate "Publish 'Agents that lie'?" about the story "agents-that-lie"
    And a "translate" run that was interrupted and recorded the outcome unknown
    When Today is read
    Then the open review requests were read once, from the open partition of the review request state index
    And the runs that need a person were read from the attention index
    And the Deliveries due were read from the due index up to the end of the day
    And the Stories scheduled to publish were read from the schedule index for the day
    And Today listed no whole table
