Feature: A publish dry run reads a tenant's records in the tenant's own scope
  A dry run of a publish reads the same site settings the real publish reads, and it checks each record's tenant against the signed-in
  site's tenant. It must carry that tenant, or every record of a tenant-owned site looks foreign to it and the preview refuses a Story that
  would publish.

  Scenario: A dry run of a publish on a tenant's site reads the site's own guidelines
    Given a site whose tenant is "machines-on-machines" has saved writing guidelines
    When the operator previews a publish through a dry run
    Then the dry run reads the saved writing guidelines
    And the dry run is in the tenant "machines-on-machines"

  Scenario: A dry run on a backend with no tenant still reads its records
    Given a site with no tenant has saved writing guidelines
    When the operator previews a publish through a dry run
    Then the dry run reads the saved writing guidelines

  Scenario: A dry run fetches a Story's stored body and never passes a write through
    Given a site whose tenant is "machines-on-machines" has saved writing guidelines
    When the operator previews a publish through a dry run that fetches the Story's stored body
    Then the dry run asked for a download slot of the stored body
    And a write the dry run does not know is refused, not performed
