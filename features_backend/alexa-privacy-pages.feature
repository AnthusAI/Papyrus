Feature: The Alexa skill's privacy policy and terms pages
  The Alexa Skills Store listing links to a privacy policy and terms of use. A site that enables the alexa plugin serves both as
  real static pages at /alexa/privacy/ and /alexa/terms/, with the site's normal header, theme and footer. They are named for the
  site's publication, say what the skill receives and keeps without claiming more, and never carry a person's email address.
  A site that does not enable the plugin gets neither page.

  Scenario: The pages exist only when the plugin is enabled
    Given a projected site with the alexa plugin enabled
    Then the site has the pages "alexa/privacy/index.html" and "alexa/terms/index.html"
    Given a projected site with no plugins
    Then the site has no page under "alexa/"

  Scenario: The pages are clean static pages with the site's chrome
    Given a projected site with the alexa plugin enabled
    Then the privacy page is a complete page with the site's header, stylesheet and footer
    And the terms page is a complete page with the site's header, stylesheet and footer
    And neither page links to an "/api/" address

  Scenario: The publication name comes from the site's configuration
    Given a projected site with the alexa plugin enabled
    Then the privacy page names the publication "Example Ledger"
    And the terms page names the publication "Example Ledger"

  Scenario: The privacy page says what the skill receives and keeps
    Given a projected site with the alexa plugin enabled
    Then the privacy page says the skill receives an anonymous Alexa user ID and device information
    And the privacy page says the skill does not receive voice recordings
    And the privacy page says account linking is optional and uses Google sign-in
    And the privacy page says votes are stored like votes made on the website
    And the privacy page says how to unlink in the Alexa app
    And each page is under 400 words

  Scenario: The contact line uses the site's configured contact page
    Given a projected site with the alexa plugin enabled and a configured contact page
    Then the privacy page links to the configured contact page

  Scenario: Without a configured contact page the footer's Contact link is named
    Given a projected site with the alexa plugin enabled
    Then the privacy page points to the footer's Contact link
    And neither page contains an email address

  Scenario: A reconcile treats the pages as plugin pages
    Then the alexa plugin protects the page prefix "alexa/" from orphan deletion

  Scenario: The static asset lists match between TypeScript and Python
    Then the TypeScript and Python lists of alexa static assets are the same

  Scenario: Every plugin Papyrus can enable is known to the projector
    Then the projector knows every plugin in the registry
    And asking the projector for the home-page plugin's files does not fail
