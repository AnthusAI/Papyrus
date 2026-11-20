Feature: Region-aware cookie consent
  A site can stop showing the cookie notice to visitors who do not need it. The page asks the site's own edge address
  once, in the background. The answer says the visitor's country and whether a notice is required. The list of regions
  that need a notice is a policy choice that the site owner owns; it is not legal advice and it must be reviewed.
  Whenever the page is unsure, it asks: it fails closed. The country is never stored, logged or sent anywhere.

  Scenario: A site that does not opt in always shows the notice
    Given a page built with a measurement id and consent mode
    Then the page never asks where the visitor is
    And the notice shows to a new visitor

  Scenario: A visitor in a regulated country sees the banner
    Given a page built with region-aware consent
    When the edge answers country "DE" with notice required
    Then the banner is shown
    And analytics stay denied until the visitor chooses

  Scenario: A visitor in an unregulated country does not see the banner and analytics follow the site standard
    Given a page built with region-aware consent
    When the edge answers country "US" with no notice required
    Then the banner is not shown
    And analytics storage is granted
    And advertising storage stays denied until the visitor accepts

  Scenario Outline: When the answer cannot be trusted, the banner is shown and everything stays denied
    Given a page built with region-aware consent
    When <problem>
    Then the banner is shown
    And analytics stay denied until the visitor chooses

    Examples:
      | problem                                              |
      | the edge answers an unknown country                  |
      | the edge does not answer within the time limit       |
      | the edge answers with something malformed            |
      | the request to the edge fails                        |

  Scenario: A stored choice skips the lookup
    Given a page built with region-aware consent
    When a visitor who rejected cookies earlier returns
    Then the page does not ask the edge anything
    And the banner is not shown
    And the stored rejection is applied

  Scenario: Deny is the default until the answer arrives
    Given a page built with region-aware consent
    When the edge has not answered yet
    Then every consent signal is denied
    And the analytics configuration has already been issued
    And the banner is not shown yet

  Scenario: The country is never sent anywhere
    Given a page built with region-aware consent
    When the edge answers country "US" with no notice required
    Then the country is not stored
    And the country is not in any analytics command
    And the only request is to the site's own consent address

  Scenario: A guarded build emits no analytics at all
    Given a guarded page built with region-aware consent
    Then the page mentions no gtag, no data layer and no analytics script
    And the page never asks where the visitor is
