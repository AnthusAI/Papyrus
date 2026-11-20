Feature: Papyrus releases say whether they affect the sites
  Every Papyrus release rebuilds all seven sites when a site bumps its pin, and
  each site build costs about ten minutes. A release that changes only the
  Python command line, the docs or the board cannot change a built site, so the
  release notes say "Affects sites: no" and a site that is behind only on such
  releases does not need a bump. Sites bump once, to the newest release, when
  at least one release since their pin affects sites.

  Scenario: a Papyrus release that changes only the Python CLI does not trigger site rebuilds
    Given a release that changed "src/papyrus_newsroom/cli.py" and "docs/site-hosting.md"
    When the release is classified
    Then the release notes say "Affects sites: no"

  Scenario: a release that changes the front end package affects sites
    Given a release that changed "packages/papyrus/src/with-papyrus.mjs" and "src/papyrus_newsroom/cli.py"
    When the release is classified
    Then the release notes say "Affects sites: yes"

  Scenario: a release that changes only tests and fixtures does not affect sites
    Given a release that changed "amplify/functions/foo/handler.test.mjs" and "amplify/fixtures/sample.json"
    When the release is classified
    Then the release notes say "Affects sites: no"

  Scenario: a site that is behind only on releases that do not affect sites needs no bump
    Given a site pinned to Papyrus "5.64.0"
    And the later releases "5.64.1" noted "Affects sites: no" and "5.64.2" noted "Affects sites: no"
    When the weekly bump is planned
    Then no bump is needed

  Scenario: one weekly bump jumps to the newest release when any release since the pin affects sites
    Given a site pinned to Papyrus "5.64.0"
    And the later releases "5.64.1" noted "Affects sites: yes" and "5.64.2" noted "Affects sites: no"
    When the weekly bump is planned
    Then the bump targets "5.64.2"
    And the site affecting releases are "v5.64.1"

  Scenario: a release without a marker is treated as affecting sites
    Given a site pinned to Papyrus "5.64.0"
    And the later release "5.64.1" noted "Bug fixes"
    When the weekly bump is planned
    Then the bump targets "5.64.1"
