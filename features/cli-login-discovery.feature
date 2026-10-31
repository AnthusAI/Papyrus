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

  Scenario: With the flag off, discovery names the main client and the broker uses it
    Given a site that has not moved the CLI onto its federation client
    When the CLI login file is requested
    Then it names the main web client and the localhost 3001 callback exactly as before

  Scenario: With the flag on, discovery names the federation client and the fixed loopback callback
    Given a site that moved the CLI onto its federation client
    When the CLI login file is requested
    Then it names the federation client, the fixed loopback callback and the remote callback

  Scenario: A site that moved to the federation client never falls back to the main client
    Given a site that moved the CLI onto its federation client but publishes no federation client
    When the CLI login file is requested
    Then the answer is "not found" explaining the site does not register the CLI callback

  Scenario: The federation client's callback list contains exactly the Prospectus callback, the loopback and the console callback
    When the federation client is synthesized with the CLI moved onto it
    Then its callbacks are each site origin's Prospectus callback, the fixed loopback and the console's cli callback

  Scenario: Sign-in on the federation client is Google-only
    When the federation client is synthesized with the CLI moved onto it
    Then only Google is admitted through the code flow and no password flow is reachable

  Scenario: A site that moves the CLI onto its federation client keeps CLI sessions for seven days
    When the federation client is synthesized with and without the CLI moved onto it
    Then with the CLI moved it keeps refresh tokens for seven days and access and ID tokens for 60 minutes
    And without it the client keeps its 60 minute refresh tokens exactly as registered

  Scenario: A site whose console has its own host registers the CLI callback there
    When the federation client is synthesized for a site whose console has its own origin
    Then the CLI callback and the Prospectus web callback are on the console origin and the loopback is unchanged
