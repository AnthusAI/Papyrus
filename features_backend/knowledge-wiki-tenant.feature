Feature: The wiki is written into the publication's own tenant
  One backend can serve several publications, each a tenant. A tenant's renders and its console read
  only the rows that carry the tenant: the Item and PublishedItem tenant id and tenant slug, and the
  type and section status keys that are stored prefixed with it. A wiki page written without that
  stamp exists but is invisible to the publication, so its public wiki index comes out empty.
  Every command that writes wiki pages therefore runs under the publication's tenant, and one that
  has no tenant refuses to write into a backend whose rows belong to one.

  Scenario: A page written for a tenant carries the tenant's stamp and the tenant's reader sees it
    Given a backend shared by two tenants
    When the wiki page "Acme Loom" is written and published as the tenant "machines-on-machines"
    Then the page's Item and PublishedItem rows both carry the tenant id "machines-on-machines"
    And both rows carry the tenant slug, the type status and the section status prefixed with the tenant
    And the tenant "machines-on-machines" lists the page among its published wiki pages
    And the tenant "other-publication" lists no wiki page

  Scenario: A wiki sync with no tenant is refused when the backend's Items belong to a tenant
    Given a backend whose Items belong to the tenant "machines-on-machines"
    When the wiki sync runs with no tenant
    Then the command is refused saying the Items belong to "machines-on-machines" and nothing is written

  Scenario: A wiki publish with no tenant is refused when the backend's Items belong to a tenant
    Given a backend whose Items belong to the tenant "machines-on-machines"
    When the wiki publish runs with no tenant
    Then the command is refused saying the Items belong to "machines-on-machines" and nothing is written

  Scenario: A backend with no tenant is written to as it always was
    Given a backend whose Items belong to no tenant
    When the wiki sync runs with no tenant
    Then the command is not refused
