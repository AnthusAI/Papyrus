@backend @monitoring-research-assignments
Feature: The router runs the research assignments editors give Stories, with nobody at a terminal
  An editor can give a Story a research assignment in the newsroom. It is an Assignment of type research.multi that names the Story and carries the editor's
  direction and the reporter context profile. Before this task, someone had to run the research from a terminal. Now a task of the monitoring service,
  research-assignments, does it. A publication turns it on in its router entry (researchAssignments, off until then), because it needs the backend to
  grant the service the fields it uses. The task runs once per publication, each in its own invocation with its own lock, and it runs in its own function with its own
  role, which holds the search and model keys. It takes that publication's open research assignments that have a Story, oldest first, marks each one running
  (claimed) with an assignment event and a lease, runs the multi-search research on it, and marks it finished (completed) or failed with the reason. A search and its synthesis take about five minutes and the fact check adds about 55 model calls, so the worker's Lambda runs up to 900 seconds, a run is not started with less than 420 seconds left, and the fact check's judge stops asking with less than 240 seconds left, so unjudged claims end unchecked and the packet is still written; the rest wait open for the next run. An assignment left running past its lease is
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
    Then while its research ran, assignment 1 was claimed by the research worker with a lease that ends 16 minutes later

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

  Scenario: A run that could not take its sources in says so plainly
    Given a backend with the open research assignments 1 on a Story
    And the research for assignment 1 finishes but could not take its sources in because the server could not write a working file
    When the research-assignments pass runs
    Then assignment 1 is completed
    And its finished note says that its sources were not added because the server could not write a working file
    And the pass result lists assignment 1 as unable to take its sources in

  Scenario: The task stops before the deadline and leaves the rest open
    Given a backend with the open research assignments 1, 2 and 3 on a Story
    And the time runs short after the first assignment
    When the research-assignments pass runs
    Then assignment 1 is completed and assignments 2 and 3 are still open
    And the pass reports that it stopped by time with 2 left open

  Scenario: A run is not started when less time is left than a search needs
    Given a backend with the open research assignments 1 on a Story
    And only 400 of the worker's 900 seconds are left
    When the research-assignments pass runs
    Then no research ran and assignment 1 is still open
    And the pass reports that it stopped by time with 1 left open

  Scenario: The fact check stops asking the judge when time is short and its claims end unchecked
    Given a fact check whose time runs short after its first judge answer
    When the claims are checked
    Then the claims not yet judged are unchecked with the reason that the run ran short of time
    And the packet is still made

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

  Scenario Outline: Everything a full run asks of the backend is granted to the worker's role, with or without a tenant
    Given the monitoring template
    And a backend <tenancy> that answers like a small real one
    When one assignment is run on the real client with its transport replaced, taking in a cited source, linking it to the Story and curating it
    Then every field it asked for is granted to the research worker's role on any publication API
    And the grant has no publish field and no updateItem or deleteItem: it may only create Items, such as a checklist step
    And the router role has gained no policy

    Examples:
      | tenancy                          |
      | with no tenant                   |
      | on the tenant "example-tenant"   |

  Scenario: An open assignment that already has a research packet is completed and not researched again
    Given a backend with the open research assignments 1 and 2 on a Story
    And assignment 1 already produces a research packet message
    When the research-assignments pass runs
    Then assignment 1 is completed with a completion time and a note that its packet already exists
    And the research ran only for assignment 2

  Scenario: A finished-run event also counts as an existing packet
    Given a backend with the open research assignments 1 on a Story
    And assignment 1 has a research.multi.completed event from a terminal run
    When the research-assignments pass runs
    Then assignment 1 is completed and no research ran

  Scenario: A terminal research run leaves its assignment completed
    Given an open research.multi assignment
    When the research run is applied from the command line and finishes
    Then the assignment is completed with a completion time and a research.completed event by the command line's actor
    And the same status change is not made twice when the worker started the run

  Scenario: A terminal research run that fails leaves its assignment failed
    Given an open research.multi assignment
    When the research run is applied from the command line and no search provider answers
    Then the assignment is failed with a research.failed event giving the plain reason
    And the research worker will not start it again

  Scenario: A failure note keeps the real reason and drops the terminal sign-in advice
    Given a research run that fails with a permission denied reason followed by a line telling the reader to sign in again at a terminal
    When the research-assignments pass runs
    Then the failed event note holds the permission denied reason
    And the note has no sign-in advice
