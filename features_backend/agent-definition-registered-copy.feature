Feature: A site's Automation record holds the registered copy of an agent definition
  The definition file in Git says what an agent is. The site's backend holds the registered copy of it on the agent's Automation record: the
  definition's id, the registered version, the digest of the definition and the definition itself as it was registered. The runner and Today read the
  registered copy on the record, never the file in Git at run time. The digest is of the effective definition, a core definition with what the site
  added to it. Registering a definition whose digest the record already holds changes nothing, and no write is made. A changed digest writes a new
  registered version, one higher than the one before; the first registration is version 1. Registering touches the registered copy and nothing else on
  the record: not whether the automation is enabled, not its trigger, and not the responsibility it was adopted onto. It never touches the agent policy
  document, so it never sets a rung, a pause or a budget. A definition is registered onto an Automation that exists, and onto one whose adopted
  responsibility is the definition's own. A dry run says what would be written and writes nothing.

  Scenario: Registering a definition records its id, version, digest and copy
    Given a site with the automation "rating-daily" and no registered definition
    When the definition "rate" is registered on "rating-daily"
    Then the automation "rating-daily" holds the registered definition "rate" at version 1
    And the registered digest of "rating-daily" is the digest of the definition "rate"
    And the registered copy on "rating-daily" is the definition "rate"
    And the registration says "registered"

  Scenario: Registering an unchanged definition changes nothing
    Given a site with the automation "rating-daily" and no registered definition
    And the definition "rate" is registered on "rating-daily"
    When the definition "rate" is registered on "rating-daily"
    Then no record was written
    And the automation "rating-daily" holds the registered definition "rate" at version 1
    And the registration says "unchanged"

  Scenario: A changed definition writes the next version
    Given a site with the automation "rating-daily" and no registered definition
    And the definition "rate" is registered on "rating-daily"
    When the definition "rate" is changed and registered on "rating-daily"
    Then the automation "rating-daily" holds the registered definition "rate" at version 2
    And the registered digest of "rating-daily" is the digest of the changed definition
    And the registered copy on "rating-daily" is the changed definition
    And the registration says "updated"

  Scenario: A site's addition to a core definition is a changed digest
    Given a site with the automation "rating-daily" and no registered definition
    And the definition "rate" is registered on "rating-daily"
    When the definition "rate" with a site must-never rule is registered on "rating-daily"
    Then the automation "rating-daily" holds the registered definition "rate" at version 2

  Scenario: The digest does not depend on the order of the fields
    Given a site with the automation "rating-daily" and no registered definition
    And the definition "rate" is registered on "rating-daily"
    When the definition "rate" is registered on "rating-daily" with its fields in another order
    Then no record was written
    And the registration says "unchanged"

  Scenario: Registering touches nothing else on the record
    Given a site with the automation "rating-daily" adopted as "rate" and disabled
    When the definition "rate" is registered on "rating-daily"
    Then the automation "rating-daily" is still adopted as "rate" and disabled
    And the automation "rating-daily" has its trigger and procedure as before
    And the site's agent policy document was not touched

  Scenario: A dry run writes nothing
    Given a site with the automation "rating-daily" and no registered definition
    When the definition "rate" is registered on "rating-daily" with a dry run
    Then no record was written
    And the registration says "registered" and is not applied
    And the automation "rating-daily" holds no registered definition

  Scenario: A definition is not registered onto an automation that does not exist
    Given a site with the automation "rating-daily" and no registered definition
    When the definition "rate" is registered on "missing"
    Then the registration is refused saying "does not exist"

  Scenario: A definition is not registered onto an automation adopted as another responsibility
    Given a site with the automation "rating-daily" adopted as "translate" and disabled
    When the definition "rate" is registered on "rating-daily"
    Then the registration is refused saying "adopted as translate"
    And no record was written

  Scenario: The registered copy is read from the record
    Given a site with the automation "rating-daily" and no registered definition
    And the definition "rate" is registered on "rating-daily"
    Then the record read for "rating-daily" shows the registered definition "rate" at version 1 with its digest and copy
