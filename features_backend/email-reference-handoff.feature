Feature: Imported newsletter articles receive cloud predictions
  An editor selects candidates from one known receipt. Imported References remain
  pending human review while the existing cloud classifier supplies predictions.

  Scenario: Exact selected References enter the existing classifier safely
    Given synthetic editor-selected newsletter References
    When their cloud handoff contracts are exercised
    Then only those References are queued idempotently and negative predictions remain reviewable
