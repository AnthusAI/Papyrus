Feature: Automations are enforced, costed and can be run by hand
  Step one recorded an automation: a trigger bound to a procedure. Step two makes the record real for monitor
  automations. The monitoring router reads the automation before it starts a procedure, so a disabled automation
  starts nothing and an automation at its limit refuses another start, each with a recorded reason. The automation's
  timeout goes to the procedure runner's deadline. The runner reports the model usage of each call, and the run
  records that usage and an estimated cost, which the history shows and compares with the advisory budget. An editor
  or an operator can also run the procedure now, and the run joins the automation's history. The procedure's other
  runs are listed apart, as started outside the automation. If the router cannot find or read an automation, it
  starts procedures exactly as it did before, because its own procedure triggers stay authoritative.

  Background:
    Given the TTAB monitor delivers two new decisions to Distinctive Mark with a procedure trigger

  Scenario: With no automation record the router starts procedures exactly as before
    Given the site has no automation record
    When the router sweeps
    Then both procedures start
    And the requests carry no timeout and no automation id
    And the trigger rows say started

  Scenario: An automation record that cannot be read does not stop a run
    Given the router cannot read the site's automation records
    When the router sweeps
    Then both procedures start
    And the requests carry no timeout and no automation id

  Scenario: A record for some other trigger is not this trigger's automation
    Given the site has an automation for a different procedure
    When the router sweeps
    Then both procedures start
    And the requests carry no timeout and no automation id

  Scenario: A disabled automation starts nothing and records why
    Given the site has the TTAB automation, disabled
    When the router sweeps
    Then no procedure starts
    And each trigger row says skipped because the automation is disabled
    And both decisions were still delivered

  Scenario: An enabled automation starts with its timeout and id
    Given the site has the TTAB automation with a timeout of 300 seconds and room for 5 at a time
    When the router sweeps
    Then both procedures start
    And the requests carry a timeout of 300 seconds and the automation id

  Scenario: A timeout longer than the runner allows is capped
    Given the site has the TTAB automation with a timeout of 5000 seconds and room for 5 at a time
    When the router sweeps
    Then the requests carry a timeout of 840 seconds

  Scenario: An automation at its limit refuses another start and records why
    Given the site has the TTAB automation with room for 1 at a time
    When the router sweeps
    Then one procedure starts
    And one trigger row says refused because the automation is at its limit of 1 at a time

  Scenario: A run started by hand counts against the limit
    Given the site has the TTAB automation with room for 1 at a time
    And a run started by hand is still running
    When the router sweeps
    Then no procedure starts
    And both trigger rows say refused

  Scenario: Finished runs and runs that never reported back stop counting
    Given the site has the TTAB automation with room for 1 at a time
    And a trigger row from an hour ago still says started
    And a trigger row that completed a minute ago
    When the router sweeps
    Then only the run started in this sweep counts against the limit

  Scenario: The runner records the usage and an estimated cost of each run
    Given a procedure run that made two GPT-6 Luna calls
    When the runner records the run
    Then the run stores its model usage per call
    And the run stores an estimated cost from the price table

  Scenario: A model with no price is listed, never counted as free
    Given a procedure run that made one call to a model with no price
    When the runner records the run
    Then the run stores its model usage with the unpriced model named
    And the run stores no cost

  Scenario: A site backend that does not have the usage fields yet still gets the outcome
    Given a site backend that refuses the usage fields
    When the runner records a run that made model calls
    Then the run is recorded as completed without its usage

  Scenario: The history shows the cost and flags a run over its advisory budget
    Given the site has the TTAB automation with a budget of 5 cents per run
    And a completed run that cost 8 cents and one that cost 2 cents
    When an editor opens the automation overview
    Then the 8 cent run is flagged as over budget
    And the 2 cent run is not flagged

  Scenario: An editor sees runs of the procedure that the automation did not start
    Given the site has the TTAB automation
    And the TTAB monitor's trigger rows
    And someone ran the procedure by hand outside the automation
    When an editor opens the automation overview
    Then the run started outside the automation is listed apart from the automation's own runs

  Scenario: Run now starts the procedure and joins the run to the automation's history
    Given the site has the TTAB automation
    When an operator runs the automation now with an input
    Then the runner is started with the automation's procedure, that input and the automation's timeout
    And a row links the run to the automation and says who started it
    And the automation's history lists that run as started by hand

  Scenario: Run now needs the input of the run when the record's input names an item
    Given the site has the TTAB automation
    When an operator runs the automation now without an input
    Then nothing is started because the input for this run is needed

  Scenario: Run now is refused for a disabled automation and at the limit
    Given the site has the TTAB automation, disabled
    When an operator runs the automation now with an input
    Then nothing is started because the automation is disabled
    Given the site has the TTAB automation with room for 1 at a time
    And a run started by hand is still running
    When an operator runs the automation now with an input
    Then nothing is started because the automation is at its limit

  Scenario: Run now can be previewed with a dry run
    Given the site has the TTAB automation
    When an operator runs the automation now with an input as a dry run
    Then nothing is started and nothing is written

  Scenario: An editor runs the automation from the console but a reader cannot
    Given the site has the TTAB automation
    When an editor runs the automation from the console with an input
    Then the console says the run started
    When a reader runs the automation from the console with an input
    Then the console refuses the request

  Scenario: An operator's IAM role reads the overview but cannot run anything
    Given the site has the TTAB automation
    And the TTAB monitor's trigger rows
    When an operator's IAM role in the same account reads the overview
    Then the overview lists the automation "Analyze new TTAB rulings"
    When an operator's IAM role in the same account runs the automation from the console
    Then the console refuses the request
    When an identity-pool user or a role from another account reads the overview
    Then both callers are refused
