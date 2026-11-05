Feature: Private hosted MCP grant service
  A publication can opt in to an isolated grant service without exposing its credentials.

  Scenario: A publication enables the grant service
    Given a publication opts into hosted MCP with its HTTPS console origin and compute role
    When its backend configuration is evaluated
    Then it has a private grant function with its own encrypted store
    And only the configured compute role is granted invocation

  Scenario: An unavailable service cannot become an invalid-token answer
    Given a publication opts into hosted MCP with its HTTPS console origin and compute role
    When the grant function cannot be reached
    Then the invocation reports a service failure separately from an invalid token
