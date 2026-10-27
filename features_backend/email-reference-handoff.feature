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

  Scenario: Branded tracking wrappers stay private until an editor resolves an article
    Given a stored newsletter with branded SendGrid article wrappers
    When its exact receipt is opened and its tracking contracts are exercised
    Then opaque tracking URLs are never offered as direct References and redirect protections remain enforced
    And a resolved legacy candidate imports and queues once while its raw wrapper is rejected

  Scenario: Actual branded route shapes remain private and HTTP failures are diagnosable
    Given a legacy branded wrapper with multiple routing path segments
    When its complete intake and bounded response contracts are exercised
    Then it imports only after resolution and failures disclose only HTTP status and hop count
