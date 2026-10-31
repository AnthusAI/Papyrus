Feature: Sign in to a Papyrus site from a machine with no browser
  An agent on a cloud machine has no browser and no long-lived keys. It runs
  `papyrus login --remote <site>`, which prints an approval URL and a short matching
  code and waits. The person opens the URL on their phone, signs in with Google on
  the site, checks the code and approves, and only the waiting CLI receives a
  session. It is stored exactly like a normal login's. This works only for a site
  that has switched it on: the site publishes a broker in its public login file.
  Every scenario drives the real cli-login broker and approval pages in memory,
  behind the site's pages function; no network, browser or keychain is involved.

  Background:
    Given the site "shipped.anth.us" has remote CLI login switched on

  Scenario: An approved sign-in gives the waiting CLI its session
    When the agent runs "papyrus login --remote shipped.anth.us"
    And the person approves it in their browser after checking the code
    Then the CLI printed only the approval URL, the matching code and who it signed in as
    And the user is signed in to "shipped.anth.us" with the same stored session a normal login makes
    And the registry file is private and holds no tokens and no broker

  Scenario: A denied sign-in gives nothing
    When the agent runs "papyrus login --remote shipped.anth.us"
    And the person denies it on the approval page
    Then the sign-in is refused saying it was denied
    And the machine has registered no site

  Scenario: A sign-in nobody approves expires
    When the agent runs "papyrus login --remote shipped.anth.us"
    And nobody approves it for ten minutes
    Then the sign-in is refused saying the approval link expired
    And the machine has registered no site

  Scenario: An approval link that was already used cannot be used again
    Given a remote sign-in that was approved and collected
    When someone opens the same approval link
    Then the page says the link is no longer valid

  Scenario: Someone who is not the expected person approves
    When the agent runs "papyrus login --remote shipped.anth.us --expect-email owner@example.com"
    And "stranger@example.com" approves it
    Then the sign-in is refused saying someone other than the expected person approved
    And the machine has registered no site

  Scenario: The pages function cannot reach the broker
    When the agent runs "papyrus login --remote shipped.anth.us"
    And the broker cannot be reached when the person opens the link
    Then the page says the link is no longer valid

  Scenario: The broker alarms notify the site's alarm topic when one is configured
    The broker has two alarms. The start ceiling alarm means too many logins were started across all callers.
    The throttled alarm means the broker reached its reserved concurrency of 10. A site that names its alarm
    topic is told when either one fires and when it recovers.
    When a site's broker is synthesized with an alarm topic
    Then both broker alarms notify that topic when they fire and when they recover

  Scenario: Without an alarm topic the synth warns once and names the setting
    A site that sets no alarm topic still gets the alarms, but nobody would hear them. The gap must be visible.
    The synth warning names the setting to apply.
    When a site's broker is synthesized without an alarm topic
    Then the alarms carry no notification and synth warns once naming the alarm topic setting

  Scenario: A site that has not switched it on says so and starts nothing
    Given the site "plain.anth.us" publishes CLI login metadata without a broker
    When the agent runs "papyrus login --remote plain.anth.us"
    Then the sign-in is refused saying the site does not publish a remote sign-in broker
    And no broker was contacted
    And the machine has registered no site

  Scenario Outline: Remote login metadata that is not trustworthy is refused before anything starts
    Given the site "odd.anth.us" publishes remote login metadata that <problem>
    When the agent runs "papyrus login --remote odd.anth.us"
    Then the sign-in is refused because the published login metadata is invalid
    And no broker was contacted
    And the machine has registered no site

    Examples:
      | problem                                  |
      | names a broker that is not HTTPS         |
      | names a broker but no remote callback    |
      | names a remote callback but no broker    |
