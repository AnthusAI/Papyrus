Feature: Imported newsletter articles receive cloud predictions
  An editor selects candidates from one known receipt. Imported References remain
  pending human review while the existing cloud classifier supplies predictions.

  Scenario: Exact selected References enter the existing classifier safely
    Given synthetic editor-selected newsletter References
    When their cloud handoff contracts are exercised
    Then only those References are queued idempotently and negative predictions remain reviewable

  Scenario: Deployed AppSync requests never fall back to submission summaries
    Given the deployed AppSync Lambda resolver event shape
    When an editor opens one exact receipt or queues its selected Reference
    Then dispatch honors the named operation and malformed requests read no monitoring records
