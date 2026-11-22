Feature: The runs that need a person are one sparse index, never a table walk
  A finished run needs a person when it failed or when its outcome is unknown, and until somebody acknowledges it. Such a run carries an
  attention key and the time it needed attention; every other run carries neither, so the attention index holds only what needs a person.
  Today and the overdue check read that index and nothing else. Acknowledging a run clears the key and the time in one update and records who
  did it and when; the run stays in the history. No code path lists the whole run table: a procedure's recent runs and the priming export read
  by the procedure index. An agent's run history is one query of the second index, its runs by automation id, newest first; it shipped a
  release after the attention index, because a deploy adds one index to a table.

  Scenario: A run that fails joins the attention list
    Given a procedure that stops with an error
    When the runner runs it
    Then the run is recorded with the attention key and the time it finished
    And the run is the only one on the attention list

  Scenario: A run that did its work needs nobody
    Given a procedure that finishes and returns a title
    When the runner runs it
    Then the run is recorded with no attention key and no attention time

  Scenario: A run that found nothing to do needs nobody
    Given a procedure that looks at a feed and returns run_outcome "nothing" with run_outcome_reason "no_new_filing"
    When the runner runs it
    Then the run is recorded with no attention key and no attention time

  Scenario: Acknowledging a failed run takes it off the attention list
    Given a failed run on the attention list
    When an operator acknowledges that run
    Then the attention list is empty
    And the run records who acknowledged it and when
    And the run is still in the history as failed

  Scenario: Acknowledging a run twice changes nothing the second time
    Given a failed run on the attention list
    When an operator acknowledges that run
    And an operator acknowledges that run again
    Then the second acknowledgement says the run was acknowledged already

  Scenario: Acknowledging a run that needs nobody changes nothing
    Given a finished run that did its work
    When an operator acknowledges that run
    Then the acknowledgement says the run needs nobody

  Scenario: The attention list is read by index and oldest first
    Given three runs that need a person, finished at different times
    When an operator lists the runs that need a person
    Then the list is the three runs, oldest first
    And the only read made was the attention index

  Scenario: The priming export reads a procedure's runs by index
    Given a site with a monitor's analysis runs
    When the priming export reads the monitor's runs
    Then the runs are read through the procedure index and no read lists the whole run table

  Scenario: A shared stack puts the tenant in front of the attention key
    Given a shared stack for the tenant "acme"
    When a failed run finishes
    Then the run is recorded with the attention key "acme#attention"

  Scenario: An agent's runs are read by its automation id, newest first
    Given the agent "announce" has three runs and another agent has one
    When an operator reads the agent "announce"'s two newest runs
    Then the runs are the agent's two newest, newest first
    And the only read made was the agent index for "announce"

  Scenario: A shared stack keeps only the tenant's runs of an agent
    Given a shared stack where the tenants "acme" and "beta" each have an agent named "announce"
    When "acme" reads the agent "announce"'s runs
    Then every run listed belongs to "acme"
