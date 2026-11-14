@backend @references-audit
Feature: Audit the relevance model against editors' decisions
  The relevance model scores each Reference with a probability that an editor will accept it. An operator can
  check those scores against what editors actually did, without changing anything: how accepted References scored
  compared with References nobody has touched, and how often an accept follows each band of score.

  Scenario: The audit counts decisions and compares scores
    Given a site whose References were scored and then reviewed by editors
    When an operator audits the relevance model
    Then the audit counts the references, the scored ones, and the accepted, rejected and untouched ones
    And the audit gives the median score of accepted and of untouched references
    And the audit gives how often an accepted reference outscored an untouched one

  Scenario: Bands run from the lowest score the model gave
    Given a site whose References were scored and then reviewed by editors
    When an operator audits the relevance model
    Then the first band starts at the lowest tenth that has a scored reference
    And each band shows how many were delivered, accepted and rejected

  Scenario: Rejected references are listed with their score and reason
    Given a site whose References were scored and then reviewed by editors
    When an operator audits the relevance model with --json
    Then each rejected reference is listed with its predicted probability and the editor's reason

  Scenario: The audit reads and never writes
    Given a site whose References were scored and then reviewed by editors
    When an operator audits the relevance model
    Then the audit changed no reference
