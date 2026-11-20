Feature: The CLI signs in on the client its site names
  A site names the sign-in client the CLI uses in its public login file. By default that is the site's main web
  client. A site that moved the CLI onto its registered Prospectus federation client names that client and a fixed
  loopback callback instead. Cognito matches callbacks exactly, so the CLI binds exactly that port and path and says
  so plainly when the port is taken. `papyrus login --print-client` shows which client a site names, as its last four
  characters only, so a move can be checked from a terminal without client ids reaching logs. These scenarios use
  synthetic login files and a real local port; no site, browser or keychain is involved.

  Scenario: With the flag off, the site names the main client and today's callback
    Given a site whose login file names the main web client and the localhost 3001 callback
    When the user runs "papyrus login --print-client" for that site
    Then the output ends the client id with its last four characters only
    And the output shows the localhost 3001 callback and signs in to nothing

  Scenario: With the flag on, the site names the federation client and the fixed loopback callback
    Given a site whose login file names the federation client and the fixed loopback callback
    When the user runs "papyrus login --print-client" for that site
    Then the output ends the client id with its last four characters only
    And the output shows the fixed loopback callback and signs in to nothing

  Scenario: The CLI refuses to start a login when the fixed loopback port is taken
    Given another program is listening on the fixed loopback port
    When the CLI waits for the sign-in callback on the fixed loopback callback
    Then it stops saying the local port is already in use and to run the login again
