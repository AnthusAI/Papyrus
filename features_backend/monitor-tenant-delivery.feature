Feature: A monitor delivers to a publication whose backend is stamped with a tenant
  Some backends serve one publication as a tenant, and the router writes and reads that backend as that tenant. A delivery must accept the
  client of the publication's own tenant and nothing else: not another tenant's client, not a tenant client for a publication that names no tenant,
  and not a client for another endpoint. References are not tenant records, so a delivery writes the same Reference either way.

  Scenario: A tenant publication's delivery succeeds
    Given a publication in the tenant "machines-on-machines" and a client for that tenant
    When a monitor delivers an item to it
    Then the delivery creates a pending Reference
    And the Reference carries no tenant field

  Scenario: A client for another tenant is refused
    Given a publication in the tenant "machines-on-machines" and a client for the tenant "another-tenant"
    When a monitor is bound to it
    Then the binding is refused and nothing is written

  Scenario: A tenant client for a publication without a tenant is refused
    Given a publication with no tenant and a client for the tenant "machines-on-machines"
    When a monitor is bound to it
    Then the binding is refused and nothing is written

  Scenario: A client for another endpoint is refused
    Given a publication in the tenant "machines-on-machines" and a client for that tenant on another endpoint
    When a monitor is bound to it
    Then the binding is refused and nothing is written

  Scenario: A publication without a tenant behaves as before
    Given a publication with no tenant and a client with no tenant
    When a monitor delivers an item to it
    Then the delivery creates a pending Reference
    And the Reference carries no tenant field
