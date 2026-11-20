Feature: The newsroom summary keeps its counts without recounting
  The newsroom shows how much there is of everything: References by decision,
  Assignments by status and by section, messages by kind. Counting every record
  each time someone opens the page would be slow and costly, so Papyrus keeps
  one summary. A full recount builds it, and after that each write sends only
  the difference it made.

  Background:
    Given a newsroom with these References
      | lineage      | version | state      | decision | corpus  |
      | ref-hospital | 1       | superseded | pending  | health  |
      | ref-hospital | 2       | current    | accepted | health  |
      | ref-budget   | 1       | current    | pending  | finance |
      | ref-rumor    | 1       | current    | rejected | finance |
    And these Assignments
      | status      | type               | section |
      | open        | research.reference | news    |
      | in_progress | reporting.candidate| news    |
      | open        | reporting.candidate|         |

  Scenario: A recount counts each Reference once, in its current version
    When the newsroom summary is recounted at "2026-11-20T15:00:00Z"
    Then the summary counts 3 "references"
    And the summary counts References by decision
      | decision | count |
      | accepted | 1     |
      | pending  | 1     |
      | rejected | 1     |
    And the summary counts References by corpus
      | corpus  | count |
      | health  | 1     |
      | finance | 2     |

  Scenario: A recount groups Assignments by status and by section
    When the newsroom summary is recounted at "2026-11-20T15:00:00Z"
    Then the summary counts 3 "assignments"
    And the summary counts Assignments by status
      | status      | count |
      | open        | 2     |
      | in_progress | 1     |
    And the summary counts Assignments by section
      | section     | count |
      | news        | 2     |
      | unsectioned | 1     |

  Scenario: A recount says when it was made and when it goes stale
    When the newsroom summary is recounted at "2026-11-20T15:00:00Z"
    Then the summary says it came from a "recount"
    And the summary goes stale at "2026-11-20T15:15:00Z"

  Scenario: The summary is one record that each recount replaces
    When the newsroom summary is recounted at "2026-11-20T15:00:00Z"
    Then the summary is stored under the single id "knowledge-raw-payload-newsroom-summary-current"

  Scenario: Creating Assignments sends only the difference
    When 2 "open" Assignments of type "research.reference" are created
    Then one summary update is sent
    And the update adds 2 to "assignments"
    And the update adds 2 to the Assignment status "open"
    And the update says it is "incremental"

  Scenario: A write that creates no Assignment sends nothing
    When 0 "open" Assignments of type "research.reference" are created
    Then no summary update is sent

  Scenario: Attaching extracted text adds to the attachment count
    When extracted text is attached to 3 References
    Then one summary update is sent
    And the update adds 3 to "referenceAttachments"

  Scenario: Registering References counts new ones and not new versions of old ones
    When a catalog import creates 2 pending References and updates 1 accepted Reference
    Then one summary update is sent
    And the update adds 2 to "references"
    And the update names the import run in its reason

  Scenario: A superseded version in an import changes no count
    When a catalog import writes only a superseded version of a Reference
    Then one summary update is sent
    And the update adds 0 to "references"

  Scenario: Comparing the stored summary with a recount shows how far it drifted
    Given the stored summary was recounted before 1 more "open" Assignment existed
    When the stored summary is compared with a fresh recount
    Then 1 count differs
    And 1 group of breakdowns differs

  Scenario: A stored summary that matches the recount shows no drift
    Given the stored summary was recounted just now
    When the stored summary is compared with a fresh recount
    Then 0 counts differ
    And 0 groups of breakdowns differ
