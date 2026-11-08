Feature: Site MCP integration
  A configured publication lets authenticated clients use its private tools
  while keeping credentials inside the site and leaving incomplete installations closed.

  Scenario: Staff use a story in chat and an MCP App
    Given a configured site with a seeded staff story
    When a verified staff client lists and calls the story tool
    Then chat receives text and structured data and the App receives its resource
    And the private credentials are not returned to the client

  Scenario: A reader cannot call staff tools
    Given a configured site with a verified reader
    When the reader lists tools and calls a staff tool
    Then only reader tools are available

  Scenario: Missing resources and failed authentication
    Given a site with incomplete MCP configuration
    Then MCP is unavailable
    And an invalid token is challenged while an unavailable verifier returns service unavailable

  Scenario: Browser and App access are explicit site choices
    Given a configured site with exact browser origins and Apps enabled
    When a browser from an allowed origin connects and another origin tries to connect
    Then only the allowed origin receives browser access
    And disabling Apps hides their resources

  Scenario: A successful write is not followed by another discovery call
    Given a configured site with a seeded staff story
    When a verified staff client saves a draft
    Then the authorized tool list is reused for the response
