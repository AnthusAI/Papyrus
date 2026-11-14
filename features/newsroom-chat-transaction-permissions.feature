Feature: Private newsroom chat transaction ownership
  The existing gateway and reply worker must check transaction ownership on their
  own chat tables without gaining access to other resources.

  Scenario: Transaction checks are limited to the two runtime role and table pairs
    Given the private chat candidate infrastructure is synthesized
    Then only the gateway messaging table and run worker conversation table allow ownership checks
