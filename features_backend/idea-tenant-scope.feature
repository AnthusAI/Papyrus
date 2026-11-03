@backend @idea-tenant-scope
Feature: A backend whose editorial records carry a tenant is written as that tenant, and one filing error does not stop the run
  A backend copied from another site with --stamp-tenant keeps the tenant of its sections and stories (Machines on Machines carries 23 sections and 20 stories
  stamped "p-apyr-us"). The editorial check refuses a record whose tenant differs from the client's, and a client with no tenant differs from every stamped
  record, so an idea that passed its check could not be filed and the run stopped. A router publication can now name its tenant, so the router reads and writes
  that backend as the tenant, and a backend Lambda is given the same tenant by its build environment. A filing that fails is recorded and the run goes on with
  the next candidate; only the same error twice in a row, with nothing filed between, stops it, and the log line says why. The router's index sync no longer
  reads every note Message, which cost the vector pass minutes before it reached the References.

  Scenario: A client with no tenant refuses a section stamped with one, and a client of that tenant accepts it
    Given a section stamped with the tenant "p-apyr-us"
    When the editorial check looks at the section with a client that has no tenant
    Then it is refused with the message that the tenant does not match the configured authoring scope
    When the editorial check looks at the section with a client of the tenant "p-apyr-us"
    Then it is accepted

  Scenario: A router publication that names its tenant gets a client of that tenant, and the others are unchanged
    Given a router with the publication "example-site" naming the tenant "p-apyr-us" and the publication "other-site" naming none
    When the router builds the clients of both
    Then the client of "example-site" was built with the tenant "p-apyr-us"
    And the client of "other-site" was built without a tenant

  Scenario: A mistyped tenant is refused rather than run unscoped
    When a router configuration names the tenant "Not A Tenant!"
    Then the configuration is refused

  Scenario: The router's index sync does not read the note Messages
    Given an index with no vectors and 3 note Messages
    When the router's index sync runs over no References
    Then no note Message was read
