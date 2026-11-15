Feature: www redirects permanently to an apex production host
  A site whose production host is an apex domain (cms.domainName with no cms.domainPrefix) is reachable at https://www.<domain>
  too. Setting cms.wwwRedirect: true makes the app shell add the www sub-domain to the app's domain association (Amplify issues and
  renews the certificate for it, and writes the DNS record in the same Route 53 zone) and a permanent (301) redirect rule from
  https://www.<domain> to https://<domain>. Amplify's host redirect keeps the path and the query string. Nothing is set by hand:
  the rule and the sub-domain are part of the app-shell stack. A site that does not set the flag synthesizes exactly as before,
  so the running Anthus sites are unchanged. A site under a shared root domain keeps using cms.redirects.
  Executable by scripts/test-www-redirect.ts.

  Scenario: An apex production host gets a www sub-domain and a 301 rule
    Given a site config with cms.domainName "example.test", no cms.domainPrefix and cms.wwwRedirect true
    When the app shell template is synthesized
    Then the domain association has sub-domains "" and "www", both on the main branch
    And the app has a custom rule from "https://www.example.test" to "https://example.test" with status 301
    And the catch-all 404-200 rule stays last

  Scenario: Without the flag nothing changes
    Given the same site config without cms.wwwRedirect
    When the app shell template is synthesized
    Then the domain association has only the apex sub-domain
    And the app has no www rule

  Scenario: The flag needs an apex production host
    Given cms.wwwRedirect true with no cms.domainName, with a cms.domainPrefix, or not a boolean
    When the site config is validated
    Then validation fails naming cms.wwwRedirect
