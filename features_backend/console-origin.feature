Feature: A site's newsroom console can live on its own host
  A Papyrus site that is served by its own edge can move its newsroom console to a separate
  host such as newsroom.example.org, while the public site keeps the site origin. The site
  names the console host as its console origin. Sign-in return URLs, the remote CLI login
  pages and the published CLI login file follow the console origin; the public site's own
  origin is untouched. A site that names no console origin behaves exactly as before.

  Scenario: Callback URLs include both origins
    Given a site whose public origin and console origin differ
    When the sign-in return URLs are expanded
    Then both origins are sign-in return URLs, each with its newsroom path and its root

  Scenario: The broker's origin is the console origin
    Given a site whose public origin and console origin differ
    When remote CLI login is planned
    Then the approval page and the callback are on the console origin

  Scenario: A site with no console origin keeps the site origin
    Given a site with no console origin
    When remote CLI login is planned
    Then the approval page and the callback are on the site origin

  Scenario: The CLI login file names the console origin on both hosts
    Given a site whose public origin and console origin differ
    When the CLI login file is fetched from the console host and from the public host
    Then both hosts return the same file, which names the console origin and its callback

  Scenario: The CLI login file is unchanged without a console origin
    Given a site with no console origin
    When the CLI login file is fetched from the public host
    Then it names the site origin and its callback
