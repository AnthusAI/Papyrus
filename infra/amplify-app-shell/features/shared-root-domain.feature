Feature: Hosts under a shared root domain
  A site can live on a host such as threat-intelligence.anth.us while the root
  domain anth.us is also associated with another Amplify app. The staging host
  is always named explicitly and is never derived from the production host.
  Executable by scripts/test-infra-site-config.ts and scripts/test-infra-synth.mjs.

  Scenario: a site under a shared root domain gets a domain association for the root with its own prefix
    Given a site config with root domain "anth.us" and domain prefix "threat-intelligence"
    When the app shell stack is synthesized
    Then there is one domain association for "anth.us"
    And it maps the main branch to the prefix "threat-intelligence"

  Scenario: staging host is explicit when the CMS host is under a shared root
    Given a site config with domain prefix "threat-intelligence" and staging domain prefix "threat-intelligence-staging"
    When the app shell stack is synthesized
    Then the same domain association also maps the staging branch to "threat-intelligence-staging"
    And no host named "staging.anth.us" is produced

  Scenario: a shared-root site without an explicit staging host is rejected
    Given a site config with a domain prefix and staging enabled but no staging domain prefix
    Then validation fails naming cms.stagingDomainPrefix

  Scenario: sites without the new fields are unchanged
    Given the pretext example site config
    When the app shell stack is synthesized
    Then each host has its own domain association with an empty prefix

  Scenario: the root domain apex redirects permanently to the primary host
    Given a site config with root domain "apyr.us", domain prefix "p" and redirects [{source: "apyr.us", status: 301}]
    When the app shell stack is synthesized
    Then the app custom rules are "https://apyr.us" to "https://p.apyr.us" with status 301, then the 404-200 catch-all
    And the domain association also maps the main branch to the empty prefix
    And no Route 53 record is created by the template

  Scenario: invalid redirects are rejected
    Given a redirects entry with status 307, an unknown key, a source outside the root domain, or the primary host as source
    Then validation fails naming cms.redirects
    And cms.redirects without cms.domainPrefix is rejected
