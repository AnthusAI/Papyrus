Feature: Database editorial guidance reaches model requests
  Current private doctrine complements learned criteria and copy-edit controls.

  Scenario: A classification request inherits only its selected desk guidance
    Given current synthetic publication doctrine and two independent desks
    When a classification request is prepared for the science desk
    Then its request contains publication and science policy without business policy

  Scenario: A changed database policy replaces stale request context
    Given current synthetic publication doctrine and two independent desks
    When a classification request is prepared for the science desk
    And the current publication policy is updated in the database
    Then the old prepared request is refused before model transmission
    And a fresh request contains the updated policy and a different context identity
