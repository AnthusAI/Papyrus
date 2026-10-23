Feature: Cloud email is independent of newsletter subscriptions
  Cloud-backed publications need a sender identity for editorial notifications
  and separately configured submission intake. Static-only sites need neither.

  Scenario: A cloud site without newsletters has its own sender setup
    Given a cloud email infrastructure case named "managed"
    When its infrastructure is synthesized locally
    Then its cloud email contract is satisfied

  Scenario: A cloud site reuses its existing sending identity
    Given a cloud email infrastructure case named "existing"
    When its infrastructure is synthesized locally
    Then its cloud email contract is satisfied

  Scenario: Static-only sites have no cloud email resources
    Given a cloud email infrastructure case named "static"
    When its infrastructure is synthesized locally
    Then its cloud email contract is satisfied

  Scenario: A cloud site must name its sender explicitly
    Given a cloud email infrastructure case named "missing"
    When its infrastructure is synthesized locally
    Then its cloud email contract is satisfied

  Scenario: A submission destination retains trusted receipt metadata
    Given a cloud email infrastructure case named "receiver"
    When its infrastructure is synthesized locally
    Then its cloud email contract is satisfied
