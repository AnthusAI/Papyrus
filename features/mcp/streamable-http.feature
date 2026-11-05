Feature: Authenticated MCP over Streamable HTTP
  A client can discover and call permitted tools without granting access to another client.

  Scenario: Discovery and calls require a bearer token on every request
    Given a seeded publication with reader and staff tools
    When an anonymous client lists or calls tools, even with a session identifier
    Then the server challenges the client and reveals no tools or results

  Scenario: A reader can discover and call only permitted tools
    Given a verified reader and a verified staff member
    When each lists tools and the reader calls a staff tool
    Then each sees only their permitted tools and the reader's call is rejected

  Scenario: A client negotiates and receives machine and human readable output
    Given a verified reader
    When the client initializes and calls a permitted tool
    Then the response contains the negotiated protocol version
    And the result contains text and structured data

  Scenario: The HTTP endpoint protects its origin and returns protocol statuses
    Given a seeded publication with MCP enabled
    When a client sends an untrusted Origin or unsupported protocol version
    Then the server rejects the request without invoking a tool
    And accepted notifications have no response body
    And a client cannot open an unsupported server event stream

  Scenario: A disabled endpoint fails closed
    Given MCP is disabled
    When a client attempts discovery
    Then no tools are exposed
