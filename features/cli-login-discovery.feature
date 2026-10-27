Feature: Sites publish their public CLI login values
  Someone who works on many Papyrus sites types `papyrus login shipped.anth.us` and
  nothing else. The CLI finds the sign-in values in a small public file the site
  serves at /.well-known/papyrus-cli.json. The file holds only public identifiers
  and points at the site's existing web app client with the http://localhost:3001/
  callback every app-shell site registers. A site whose client does not register
  that callback serves no such file, so the CLI can say so plainly. No backend
  change is needed. These scenarios use synthetic Amplify outputs and no server.

  Scenario: A site publishes its login values
    Given a site whose web client registers the localhost 3001 callback
    When the CLI login file is requested
    Then it names the site's own origin, Cognito issuer, web client id, hosted sign-in domain, GraphQL endpoint and the localhost 3001 callback
    And it contains only public fields

  Scenario: The published origin comes from site configuration, never the request
    Given a site whose web client registers the localhost 3001 callback
    When the CLI login file is requested through a different host name
    Then the published origin is still the configured site origin

  Scenario: A site whose client does not register the callback publishes nothing
    Given a site whose web client does not register the localhost 3001 callback
    When the CLI login file is requested
    Then the answer is "not found" explaining the site does not register the CLI callback

  Scenario: A site without sign-in outputs publishes nothing
    Given a site whose Amplify outputs have no sign-in section
    When the CLI login file is requested
    Then the answer is "not found" explaining the site does not register the CLI callback

  Scenario: A site that cannot tell its own origin refuses to publish
    Given a site whose public origin is not configured
    When the CLI login file is requested
    Then the answer is "service unavailable"
