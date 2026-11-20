Feature: Recounting the newsroom summary from the command line
  The newsroom summary is kept current by small differences, and differences can
  be lost. `papyrus sections recount-summary` counts every record again and
  replaces the stored summary. With `--dry-run` it only reports how far the
  stored summary had drifted. When the recount cannot read the newsroom's
  messages it stops and names the command that repairs them.

  Background:
    Given a newsroom that holds 2 References, 3 Assignments and 1 message
    And a stored summary that counts 2 References and 1 Assignment

  Scenario: A dry run reports the drift and writes nothing
    When an operator runs the recount with "--dry-run --json"
    Then the recount reports the action "dry-run"
    And the recount reports that 2 counts changed
    And the recount says the stored summary was not updated
    And nothing is written to the newsroom

  Scenario: A recount replaces the stored summary and its attachment
    When an operator runs the recount with "--json"
    Then the recount says the stored summary was updated
    And the summary record is written once
    And the summary's counts are uploaded once as its attachment

  Scenario: The stored summary keeps the date it was first created
    When an operator runs the recount with "--json"
    Then the written summary record was created at "2026-11-01T00:00:00Z"

  Scenario: A recount without JSON output lists each count that changed
    When an operator runs the recount with "--dry-run"
    Then the recount prints the line "count	assignments	1	->	3"
    And nothing is written to the newsroom

  Scenario: A message with no status stops the recount and names the repair
    Given one message in the newsroom has no status
    When an operator runs the recount with "--json"
    Then the recount stops and tells the operator to run "papyrus sections repair-message-status"
    And nothing is written to the newsroom

  Scenario: The retired apply flag is refused
    When an operator runs the recount with "--apply"
    Then the recount stops and says writes now run by default
    And nothing is written to the newsroom
