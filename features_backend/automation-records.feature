Feature: Automation records describe what starts a procedure by itself
  An automation is a named record in a site's backend: a trigger, the procedure it starts, and the input
  that procedure is given. Step one wraps what already runs. Distinctive Mark's TTAB monitor already starts
  its ruling-analysis procedure for each new decision through the monitoring router's procedure triggers,
  and a monitor automation mirrors that trigger without changing it. The record never starts anything.
  Editors and admins read an automation's recent runs, joined from the monitor's trigger rows and the
  procedure runs recorded in the site's backend. Only monitor automations are live; the other kinds are
  stored and say they are not yet supported.

  Scenario: An operator records the TTAB monitor's trigger as an automation
    Given a site backend with no automations
    When an operator creates the automation "distinctive.ttab" for monitor "ttab" delivering to "distinctive" running "distinctive.ttab.ruling-analysis"
    Then the automation is stored enabled with the router's input template
    And the automation is a supported monitor automation

  Scenario: The router's trigger matches the record
    Given a site backend with the TTAB automation
    And the TTAB monitor's router starts "distinctive.ttab.ruling-analysis" with the same input
    When an editor opens the automation overview
    Then the automation's router link is "linked"

  Scenario: A record that disagrees with the router says so
    Given a site backend with the TTAB automation
    And the TTAB monitor's router starts "distinctive.ttab.ruling-analysis" with a different input
    When an editor opens the automation overview
    Then the automation's router link is "input_differs"

  Scenario: Schedule, event and manual automations are stored but not live
    Given a site backend with no automations
    When an operator creates a "schedule" automation "digest" running "distinctive.weekly-digest"
    Then the automation is stored
    And the automation is marked "not yet supported"
    And the automation has no run history

  Scenario: A record that cannot work is refused with a reason
    Given a site backend with no automations
    When an operator creates a monitor automation whose input uses the placeholder "{nonsense}"
    Then the creation is refused because of an unknown placeholder
    And no automation is stored

  Scenario: Recent runs join the monitor's trigger rows with the procedure runs
    Given a site backend with the TTAB automation and its recorded runs
    And the TTAB monitor's trigger rows
    When an editor opens the automation overview
    Then the newest run is listed first
    And the completed run for "97752244-EXA_26" took 185 seconds and created the story "story-lineage-1"
    And the failed run for "97752245-EXA_26" shows the error "the opinion could not be downloaded"
    And the run for "97752246-EXA_26" is started with no run record yet
    And the run for "97752247-EXA_26" could not start
    And the run for "97752248-EXA_26" says its run record was not found

  Scenario: Items that already had a Reference are counted, not listed as runs
    Given a site backend with the TTAB automation and its recorded runs
    And the TTAB monitor's trigger rows
    When an editor opens the automation overview
    Then 2 items are reported as not started because the Reference already existed
    And no listed run has the status "notTriggered"

  Scenario: Cost is unknown and the page says where it would come from
    Given a site backend with the TTAB automation and its recorded runs
    And the TTAB monitor's trigger rows
    When an editor opens the automation overview
    Then every run reports its cost as unknown
    And the cost note says the procedure runner does not record token use or cost

  Scenario: Enabled is a display flag the router does not read
    Given a site backend with the TTAB automation
    And the TTAB monitor's trigger rows
    When an operator disables the automation "distinctive.ttab"
    Then the record shows the automation as disabled
    And the record says enabled is display only until the router honours it
    And the router's configuration and the trigger rows are unchanged

  Scenario: Only editors and admins can read automations
    Given a site backend with the TTAB automation
    When a reader opens the automation overview
    Then the request is refused
    When an admin opens the automation overview
    Then the overview lists the automation "Analyze new TTAB rulings"

  Scenario: A site never reads another publication's runs
    Given a site backend with the TTAB automation and its recorded runs
    And the TTAB monitor's trigger rows
    When an editor of a different site opens the automation overview
    Then the automation has no run history because it belongs to another publication
    And the trigger rows of the other publication are never returned

  Scenario: Automations still list when monitoring is not connected
    Given a site backend with the TTAB automation
    And monitoring is not connected to the site's account
    When an editor opens the automation overview
    Then the overview lists the automation "Analyze new TTAB rulings"
    And the automation says run history cannot be shown

  Scenario: The history never exposes the runner's request, endpoints or key parameter
    Given a site backend with the TTAB automation and its recorded runs
    And the TTAB monitor's trigger rows
    When an editor opens the automation overview
    Then the overview contains no endpoint or secret parameter name

  Scenario: An operator lists and inspects automations from the command line
    Given a site backend with the TTAB automation
    And the TTAB monitor's trigger rows
    When an operator runs "automations list"
    Then the output has one line for "distinctive.ttab" showing monitor, the procedure, enabled and the last run status
    When an operator runs "automations show --id distinctive.ttab"
    Then the output says enabled is display only until the router honours it
    And the output says the limits are recorded only

  Scenario: An operator reads an automation's run history from the command line
    Given a site backend with the TTAB automation and its recorded runs
    And the TTAB monitor's trigger rows
    When an operator runs "automations runs --id distinctive.ttab"
    Then the output lists the run for "97752244-EXA_26" with its run id and story
    And the output reports 2 items not started because the Reference already existed
    And the output says cost is not recorded

  Scenario: Run history needs the monitoring table but listing does not
    Given a site backend with the TTAB automation
    And monitoring is not connected to the site's account
    When an operator runs "automations list"
    Then the output has one line for "distinctive.ttab" showing monitor, the procedure, enabled and the last run status
    When an operator runs "automations runs --id distinctive.ttab"
    Then the command is refused because it needs the monitoring table

  Scenario: A dry run previews a new automation and writes nothing
    Given a site backend with no automations
    When an operator runs "automations create --id new.one --title New --monitor ttab --publication distinctive --procedure distinctive.ttab.ruling-analysis --dry-run"
    Then the output says it was a dry run
    And no automation is stored

  Scenario: Updating an automation changes only what the operator sets
    Given a site backend with the TTAB automation
    When an operator runs "automations update --id distinctive.ttab --enabled false --budget-usd 3"
    Then the automation "distinctive.ttab" is disabled with a budget of 3 dollars per run
    And its trigger and input template are unchanged
