@backend @request-meter
Feature: Every process counts its AppSync requests, says who made them, and warns when it spends more than its input justifies
  AppSync bills per request, and the expensive days came from loops that sent one request per row. So every process that talks to AppSync
  through the Python client counts its requests by caller (the command, or the Lambda and its task, or the stage), model and operation,
  and says so in one line when it ends: on stderr for the command line, as a structured log line for a Lambda or a stage. Each caller has
  a budget that grows with its input: a base plus an amount for each id it was given or each item it processed, never one fixed number
  for everything. A process over its budget prints a warning that names the caller, the count and the budget, and carries on. Stopping
  is a switch that is off by default; it is meant to be turned on after about a week of warnings (not before 2026-11-13). A named
  sweep or backfill declares itself, is counted, and is never held to the budget. "--budget N" raises one command's budget and is logged.
  A read of every row of a model outside a named sweep is logged as an unbounded list, and a test fails when a new one appears in the
  code. Nothing here touches AWS: the backend is a fake.

  Scenario: A command prints one summary line of its requests by caller
    Given a command named "references show" given 2 ids
    When it makes 2 reads of a Reference
    Then stderr has one line that starts "papyrus requests: cli:references show total=2"
    And the line names "Reference.GetReference x2"

  Scenario: A Lambda writes a structured summary
    Given a Lambda named "router" invoked for the task "auto-accept"
    When it makes 2 reads of a Reference
    Then its log has one JSON line with event "papyrus_request_summary", caller "lambda:router:auto-accept" and 2 requests

  Scenario: The budget grows with the input
    Given a command named "references show" given 1 id
    And another run of the same command given 10 ids
    Then the second budget is 9 times the per-id amount larger than the first

  Scenario: A process over its budget warns once and carries on
    Given a command named "references show" with a budget of 5
    When it makes 12 reads of a Reference
    Then all 12 reads were made
    And stderr has exactly one warning that names "references show" and the budget of 5

  Scenario: Stopping is off unless it is switched on
    Given a command named "references show" with a budget of 2
    When it makes 4 reads of a Reference
    Then no error was raised
    When the stop switch is on and a command with a budget of 2 makes 4 reads
    Then the run is stopped with a budget error

  Scenario: A named sweep is counted but never held to the budget
    Given a command named "references show" with a budget of 2
    When it makes 10 reads of a Reference inside the sweep "all-references"
    Then all 10 reads were counted and none was held to the budget
    And stderr has no warning

  Scenario: A whole-table list outside a sweep is reported
    Given a Lambda named "router" invoked for the task "route"
    When it lists every Reference twice, and once more inside the sweep "all-references"
    Then its log says once that the unbounded list of Reference was made outside a named sweep
    And its summary counts 2 unbounded lists of Reference

  Scenario: A new whole-table read in the code fails the build
    Given the allowlist of files that may read a whole table
    Then no file reads more whole tables than the allowlist records

  Scenario: The video capture commands find the site's corpus through an index
    Given a signed-in site with one canonical publication corpus
    When capture-transcripts, capture-thumbnails and repair-titles resolve their corpus without a --corpus-key
    Then each covers the canonical corpus and the request meter records no unbounded list of KnowledgeCorpus
