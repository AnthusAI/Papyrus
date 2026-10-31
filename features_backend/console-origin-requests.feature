Feature: A console on its own host may make same-origin requests
  A Papyrus site can serve its newsroom console from its own host while the public site keeps
  the site origin. The console's curation and chat requests carry the console host as their
  Origin, so the same-origin checks accept exactly two origins: the site origin and, when the
  site names one, the console origin. Matching is exact, with no wildcards. A site that names
  no console origin accepts only its own origin, as before.

  Scenario: The console origin is accepted when configured
    Given a site whose public origin and console origin differ
    When a request arrives from the console origin
    Then the same-origin check accepts it

  Scenario: A foreign origin is still refused
    Given a site whose public origin and console origin differ
    When a request arrives from a foreign origin
    Then the same-origin check refuses it

  Scenario: A site with no console origin is unchanged
    Given a site with no console origin
    When a request arrives from the console host's would-be origin
    Then the same-origin check refuses it
