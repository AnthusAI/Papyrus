Feature: Sites publish their public CLI login values
  Someone who works on many Papyrus sites types `papyrus login shipped.anth.us` and
  nothing else. The CLI finds the sign-in values in a small public file the site
  serves at /.well-known/papyrus-cli.json. The file holds only public identifiers.
  A site whose backend never opted in to CLI login serves no such file, so the CLI
  can say so plainly. These scenarios use synthetic Amplify outputs and no server.

  Scenario: A site with a native CLI client publishes its login values
    Given a site whose backend declared a native CLI client
    When the CLI login file is requested
    Then it names the site's own origin, Cognito issuer, client id, hosted sign-in domain, GraphQL endpoint and loopback callback
    And it contains only public fields

  Scenario: The published origin comes from site configuration, never the request
    Given a site whose backend declared a native CLI client
    When the CLI login file is requested through a different host name
    Then the published origin is still the configured site origin

  Scenario: A site with no native CLI client publishes nothing
    Given a site whose backend declared no native CLI client
    When the CLI login file is requested
    Then the answer is "not found" explaining the site has no native CLI sign-in client

  Scenario: An unsafe callback is never published
    Given a site whose declared CLI callback is not a loopback address
    When the CLI login file is requested
    Then the answer is "not found" explaining the site has no native CLI sign-in client

  Scenario: A site that cannot tell its own origin refuses to publish
    Given a site whose public origin is not configured
    When the CLI login file is requested
    Then the answer is "service unavailable"

  Scenario: The native CLI client is Google-only with a renewable session
    Given a site that opts in to CLI login with a loopback callback
    Then its Cognito client has no secret and admits only Google through the authorization code flow
    And it registers exactly the loopback callback and allows only refresh-token authentication
    And token revocation is on and the refresh session lasts 30 days by default

  Scenario: A backend cannot declare a non-loopback CLI callback
    Given a backend that tries to opt in with a callback that is not a fixed loopback port
    Then the backend refuses to build the client
