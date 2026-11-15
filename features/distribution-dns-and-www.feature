Feature: A site that creates its own distribution can point its hosts at it and send www to the apex
  A site on the S3 projection can have its backend create the CloudFront distribution with `publication.distribution.create`.
  Two more settings finish the job without a hand-made stack. `dnsRecords` writes an A and an AAAA alias record for every alias in
  the hosted zone named by `acm`. `wwwRedirect` makes the edge answer a request for www.<host> with a 301 to https://<host>, keeping
  the path and the query. Both are off unless set, so a site that does not set them synthesizes exactly as before.
  These scenarios run in scripts/test-s3-projection-publication.ts and scripts/test-redirect-rules.ts.

  Scenario: Alias records are written for every alias
    Given a distribution that is created with the aliases "example.org" and "www.example.org", an acm hosted zone and dnsRecords true
    When the backend is synthesized
    Then the stack has an A record and an AAAA record for each alias, in that zone, aliased to the distribution

  Scenario: Without dnsRecords no record is written
    Given a distribution that is created with an alias and an acm hosted zone, and dnsRecords not set
    When the backend is synthesized
    Then the stack has no Route 53 record

  Scenario: dnsRecords needs the zone
    Given dnsRecords true with no acm hosted zone
    Then the configuration is refused naming dnsRecords

  Scenario: www goes to the apex, path and query kept
    Given a distribution with wwwRedirect true
    When a viewer asks for https://www.example.test/articles/x/?a=1
    Then the edge answers 301 with Location https://example.test/articles/x/?a=1

  Scenario: The apex and a site without wwwRedirect are served as usual
    Given a request for the apex host, or any host on a site that did not set wwwRedirect
    Then the edge serves the page and sends no redirect

  Scenario: wwwRedirect needs both hosts
    Given wwwRedirect true and aliases that do not list both example.org and www.example.org
    Then the configuration is refused naming wwwRedirect
