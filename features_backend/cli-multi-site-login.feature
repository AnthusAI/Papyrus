Feature: Sign in to many Papyrus sites from one CLI
  A person who works across several Papyrus sites signs in by site name, stays
  signed in to all of them at once, and each request uses the session of the site
  that owns the API it talks to. Sign-in values are read from the site itself, so
  nobody copies client ids around. Every scenario uses isolated providers and
  secure stores; no real site, browser or keychain is involved.

  Scenario: Signing in by site name reads the site's public login file
    Given the sites "a.anth.us" and "b.anth.us" each publish CLI login metadata
    When the user runs "papyrus login a.anth.us"
    Then the CLI fetched "https://a.anth.us/.well-known/papyrus-cli.json" over HTTPS
    And the user is signed in to "a.anth.us" only
    And the registry file is private and holds no tokens

  Scenario: A site with no native CLI client says so
    Given the site "c.anth.us" publishes no CLI login file
    When the user tries to sign in to "c.anth.us"
    Then the sign-in is refused saying the site does not publish CLI login
    And no site is registered

  Scenario Outline: Untrustworthy login metadata is refused before anything is saved
    Given the site "a.anth.us" publishes login metadata that <problem>
    When the user tries to sign in to "a.anth.us"
    Then the sign-in is refused with a message about invalid or mismatched metadata
    And no site is registered

    Examples:
      | problem                                   |
      | names a different publication             |
      | contains an unknown extra field           |
      | omits the client id                       |
      | uses a non-HTTPS OAuth domain             |
      | uses a non-loopback callback              |
      | is larger than the size cap               |
      | answers with a redirect                   |

  Scenario: Several sites stay signed in at once
    Given the sites "a.anth.us" and "b.anth.us" each publish CLI login metadata
    When the user runs "papyrus login a.anth.us b.anth.us"
    Then the user is signed in to "a.anth.us" and "b.anth.us"

  Scenario: Each request uses the session of the site that owns the endpoint
    Given the user is signed in to "a.anth.us" and "b.anth.us"
    When a request is made to the GraphQL endpoint of "b.anth.us"
    Then the session of "b.anth.us" supplied the credentials

  Scenario: A request for an endpoint no signed-in site owns names what to do
    Given the user is signed in to "a.anth.us" and "b.anth.us"
    When a request is made to an unknown GraphQL endpoint
    Then the request is refused naming the signed-in sites and the login command
    And the operator AWS credentials were not used

  Scenario: A signed-out site tells the user which site to log in to
    Given the user is signed in to "a.anth.us" and "b.anth.us"
    When the user runs "papyrus logout a.anth.us"
    And a request is made to the GraphQL endpoint of "a.anth.us"
    Then the request is refused with "papyrus login a.anth.us"
    And the session of "b.anth.us" is still signed in

  Scenario: Logging in to all registered sites
    Given the user is signed in to "a.anth.us" and "b.anth.us"
    When the user runs "papyrus login --all"
    Then both sites went through browser sign-in again

  Scenario: One failed site does not stop login --all
    Given the user is signed in to "a.anth.us" and "b.anth.us"
    And the browser sign-in for "a.anth.us" will be declined
    When the user runs "papyrus login --all"
    Then "b.anth.us" was signed in again
    And the command reports "a.anth.us" as failed and exits with an error

  Scenario: whoami lists every signed-in site
    Given the user is signed in to "a.anth.us" and "b.anth.us"
    When the user runs "papyrus whoami"
    Then one status line is printed for each of "a.anth.us" and "b.anth.us"
    And no token appears in the output

  Scenario: Logging out of one site or of all sites
    Given the user is signed in to "a.anth.us" and "b.anth.us"
    When the user runs "papyrus logout a.anth.us"
    Then only "a.anth.us" lost its stored session
    When the user runs "papyrus logout --all"
    Then no site has a stored session

  Scenario: Logging out without naming a site is ambiguous when several are signed in
    Given the user is signed in to "a.anth.us" and "b.anth.us"
    When the user runs "papyrus logout" without a site
    Then the command asks the user to name a site
    And both sites keep their stored sessions

  Scenario: A session from the single-site CLI survives the upgrade
    Given a single-site selection file and keychain secret written by the previous CLI for "old.anth.us"
    When a request is made to the GraphQL endpoint of "old.anth.us"
    Then the existing session is used without signing in again
    And a later login to "b.anth.us" keeps "old.anth.us" registered

  Scenario: A site cannot take over another site's endpoint
    Given the user is signed in to "a.anth.us" and "b.anth.us"
    When the site "evil.anth.us" publishes the GraphQL endpoint of "a.anth.us" and the user signs in to it
    Then the sign-in is refused saying the endpoint is already registered for "a.anth.us"

  Scenario: Doctor reports version, install kind and the health of each site
    Given the user is signed in to "a.anth.us" and "b.anth.us"
    And "b.anth.us" has an expired session
    When the user runs "papyrus doctor"
    Then it reports the installed version and a newer release on PyPI
    And it reports whether the CLI runs from a tool install or a virtualenv
    And it reports "a.anth.us" as valid and "b.anth.us" as needing "papyrus login b.anth.us"
    And the report contains no tokens and no email addresses

  Scenario: Doctor works offline
    Given PyPI cannot be reached
    When the user runs "papyrus doctor"
    Then it says the latest version is unknown and still reports the install kind

  Scenario: Doctor explains how to get papyrus on the PATH from a virtualenv
    Given the CLI is running from a virtualenv that is not on the PATH
    When the user runs "papyrus doctor"
    Then it recommends installing with pipx or uv tool
