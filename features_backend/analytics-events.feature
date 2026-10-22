Feature: Privacy-safe Google Analytics events
  A publication that sets a GA4 measurement id gets Consent Mode v2, a first-party banner and a small, fixed set of
  events. No identity ever reaches Google Analytics: not in event parameters, not in the page address it records, and
  not as a user id. A publication without a measurement id gets none of it.

  Scenario: A site without a measurement id has no analytics
    Given a page built without a measurement id
    Then the page mentions no gtag, no data layer and no analytics script

  Scenario: Analytics are loaded after the consent defaults
    Given a page built with a measurement id and consent mode
    Then the consent defaults come before the analytics loader
    And the location redaction comes before the analytics loader

  Scenario: Query tokens and identities are removed from the recorded address
    Given a page built with a measurement id and consent mode
    When a visitor opens "https://site.example/newsletter/confirmed/?token=abc123&lists=weekly&email=a%40b.example&ss=ss1_abc#top"
    Then the recorded page location is "https://site.example/newsletter/confirmed/?lists=weekly"

  Scenario: A marked call to action reports its text, place and destination without a query string
    Given a page built with a measurement id and consent mode
    When a visitor clicks the link "Talk to us" marked "hero" to "https://anth.us/engage/?solution=Shipped&cta=hero&token=abc"
    Then the event "cta_click" is sent with link_url "anth.us/engage/" and cta_location "hero"

  Scenario: A sponsor unit is never a call to action
    Given a page built with a measurement id and consent mode
    When a visitor clicks the link "Visit" marked "hero" to "https://x.example/a" inside a sponsor unit
    Then no event is sent

  Scenario: Only the reserved events and their listed parameters are sent
    Given a page built with a measurement id and consent mode
    When the page reports "sign_up" with method "newsletter" and a user_id
    And the page reports "page_view" with no parameters
    Then exactly these events were sent: "sign_up"
    And no event carries a user_id

  Scenario: A docs site turns analytics on with one setting
    Given a documentation site built with the measurement id "G-ABC123DEF4"
    Then its pages carry the consent banner, the cookie settings link and a privacy link
    And a documentation site built without one carries none of them
