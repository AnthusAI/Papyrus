@backend @router-tenant-grants
Feature: The router role may use every field a tenant client asks for
  A router publication that names its tenant reads and writes its backend with a tenant client. That client asks AppSync for a field the untenanted one does not:
  the lookup of a story or doctrine record by slug becomes the lookup by tenant slug. The router role is allowed an explicit list of fields, and a field missing
  from it fails the whole idea run at once with "Permission denied". The fields of a run are recorded on the real client with its transport replaced, never listed
  by hand, and each must be granted on that publication's API by the monitoring template.

  Scenario Outline: Everything an idea run asks of a tenant publication is granted
    Given a publication "machines-on-machines" whose router entry names its tenant
    When one monitor-stories pass runs on the tenant client with context packs <packs>
    Then every field it asked for is granted to the router on that publication's API

    Examples:
      | packs |
      | off   |
      | on    |

  Scenario: The fields a tenant adds are recorded, and each is granted
    Given a publication "machines-on-machines" whose router entry names its tenant
    When the fields of a pass on the tenant client are compared with those of a pass on a client with no tenant
    Then the tenant client asked additionally for the tenant slug lookup
    And every field the tenant client added is granted to the router

  Scenario: The doctrine lookup uses the tenant's own slugs
    Given a publication "machines-on-machines" whose router entry names its tenant
    When the editorial doctrine is looked up on the tenant client
    Then every slug asked for begins with "machines-on-machines#"
