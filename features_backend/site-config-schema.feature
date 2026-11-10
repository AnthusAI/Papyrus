Feature: A shared-tier site is described by a SiteConfig, never by code
  Launching a site on the shared tier has to be a data change only. The settings an owner may change are a small, versioned
  SiteConfig document with a JSON schema: the site's name, tagline and purpose line, its sections, the order of its navigation, the home
  template, footer links, the analytics id, the consent region policy and which feature blocks are on. A dedicated site's
  projection.json is a superset of that document, and one converter turns it into a SiteConfig (keeping everything a shared tenant
  cannot set aside) and back, so both tiers run one schema. Anything outside the v1 surface, such as hooks, custom CSS, sizes, URL
  style or plugins, is refused and the owner is told which setting it was.

  Scenario: TI's settings convert and render the same
    Given Threat Intelligence's projection.json for conversion
    When it is converted to a SiteConfig and back
    Then validation passes and the rendered home page is unchanged

  Scenario: Machines on Machines converts and renders the same
    Given Machines on Machines's projection.json for conversion
    When it is converted to a SiteConfig and back
    Then validation passes and the rendered home page is unchanged

  Scenario: TI's projection.json converts to a valid SiteConfig
    Given Threat Intelligence's projection.json for conversion
    When it is converted to a SiteConfig
    Then the SiteConfig is valid
    And the hooks stay behind with the dedicated site

  Scenario: A setting outside the v1 surface is refused for a shared tenant
    Given a shared tenant's SiteConfig with a custom CSS file
    When it is validated
    Then it is refused naming the setting

  Scenario: Code and layout settings are refused for a shared tenant
    Given a shared tenant's SiteConfig with hooks, plugins and a URL style
    When it is validated
    Then it is refused naming the setting
