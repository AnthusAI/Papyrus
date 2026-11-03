@backend @monitoring-research-assignments
Feature: The router runs the research assignments editors give Stories, with nobody at a terminal
  An editor can give a Story a research assignment in the newsroom. It is an Assignment of type research.multi that names the Story and carries the editor's
  direction and the reporter context profile. Before this task, someone had to run the research from a terminal. Now a task of the monitoring service,
  research-assignments, does it. A publication turns it on in its router entry (researchAssignments, off until then), because it needs the backend to
  grant the service the fields it uses. The task runs once per publication, each in its own invocation with its own lock, and it runs in its own function with its own
  role, which holds the search and model keys. It takes that publication's open research assignments that have a Story, oldest first, marks each one running
  (claimed) with an assignment event and a lease, runs the multi-search research on it, and marks it finished (completed) or failed with the reason. A search takes
  minutes, so the task stops starting new ones when the time is short and leaves the rest open for the next run. An assignment left running past its lease is
  failed with a reason, so it cannot hang, and a failed assignment is never retried by the task, because a run spends search and model calls. No fixed limit and no budget gate
  bounds it: a person asked for each run. The backend, the clock and the research are fakes in these scenarios.

  Scenario: Open research assignments with a Story run oldest first and finish
    Given a backend with the open research assignments 2 and 1 on a Story
    When the research-assignments pass runs
    Then the research ran for assignments 1 and 2 in that order
    And both assignments are completed
    And assignment 1 has a claim event and a finished event

  Scenario: An assignment is marked running before its research starts
    Given a backend with the open research assignments 1 on a Story
    When the research-assignments pass runs
    Then while its research ran, assignment 1 was claimed by the research worker with a lease that ends 11 minutes later

  Scenario Outline: An assignment that is not an editor's research assignment on a Story is left alone
    Given a backend whose only assignment is <kind>
    When the research-assignments pass runs
    Then no research ran and no event was written

    Examples:
      | kind                                  |
      | open and has no Story                 |
      | open and has the researcher profile   |
      | already completed                     |
      | a research.candidate assignment       |

  Scenario: A failed run records its reason and the others still run
    Given a backend with the open research assignments 1, 2 and 3 on a Story
    And the research for assignment 1 reports "no search provider answered"
    And the research for assignment 2 raises an error
    When the research-assignments pass runs
    Then assignments 1 and 2 are failed with their reasons in a failed event
    And assignment 3 is completed

  Scenario: The task stops before the deadline and leaves the rest open
    Given a backend with the open research assignments 1, 2 and 3 on a Story
    And the time runs short after the first assignment
    When the research-assignments pass runs
    Then assignment 1 is completed and assignments 2 and 3 are still open
    And the pass reports that it stopped by time with 2 left open

  Scenario: An assignment left running past its lease is failed so it cannot hang
    Given a backend with assignment 1 claimed with a lease that ended a minute ago
    And assignment 2 claimed with a lease that ends in five minutes
    When the research-assignments pass runs
    Then assignment 1 is failed with the reason that its time ran out
    And assignment 2 is still claimed
    And no research ran

  Scenario: A publication runs it only when it turned it on
    Given a router whose publications "a-site" and "b-site" turned research assignments on and "off-site" did not
    When the research-assignments task runs without naming a publication
    Then it started one run for "a-site" and "b-site"
    And the research fan-out took no lock and wrote no receipt

  Scenario: One publication's run has its own lock
    Given a router whose publications "a-site" turned research assignments on
    When the research-assignments task runs for "a-site"
    Then its open assignment is completed
    And the routing pass lock is free after the research run
    And the research-assignments lock of "a-site" is free again

  Scenario: Everything a full run asks of the backend is granted to the worker's role
    Given the monitoring template
    When one assignment is run on the real client with its transport replaced
    Then every field it asked for is granted to the research worker's role on any publication API
    And the router role has gained no policy
