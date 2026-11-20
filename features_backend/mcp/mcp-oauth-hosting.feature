Feature: A publication opts in to a private grant service for hosted MCP
  A publication that wants people to connect an MCP client turns on an isolated grant service. The service keeps the publication's
  credentials to itself, and when it cannot be reached the client is told the service is unavailable. It is never told its token
  is invalid, because that would make a working client throw its grant away.

  Scenario: A publication enables the grant service
    Given a publication opts into hosted MCP with its HTTPS console origin and compute role
    When its backend configuration is evaluated
    Then it has a private grant function with its own encrypted store
    And only the configured compute role is granted invocation

  Scenario: An unavailable service cannot become an invalid-token answer
    Given a publication opts into hosted MCP with its HTTPS console origin and compute role
    When the grant function cannot be reached
    Then the invocation reports a service failure separately from an invalid token
