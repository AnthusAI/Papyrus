Feature: Copying one Papyrus site's backend data into another site's backend
  Ryan is moving the read.p.apyr.us publication (site id p-apyr-us) to a new site, Machines on Machines,
  which has its own new backend. `papyrus ops site copy` reads every model's DynamoDB table in the source
  backend and writes the records to the same model's table in the target backend, with the media objects.
  Records keep their fields, timestamps and __typename. Only ids and fields that embed the old corpus key
  (which is also the site id) change, and Reference ids never change because the shared Cyclotron trains on
  them. A dry run is the default and writes nothing; writing needs an explicit --apply.

  Background:
    Given a source site backend holding records of the site p-apyr-us
    And an empty target site backend with the same tables

  Scenario: A dry run is the default and writes nothing
    When I run the site copy without --apply
    Then the report counts the source records per model
    And the target tables hold no records
    And the target bucket holds no objects

  Scenario: Passing both --apply and --dry-run is refused
    When I run the site copy with --apply and --dry-run
    Then the command is refused before anything is read

  Scenario: The corpus key is rewritten in ids and fields that embed it
    When I run the site copy with --apply
    Then the Item "p-apyr-us.item-x" is in the target as "machines-on-machines.item-x"
    And the Section "p-apyr-us#security" is in the target as "machines-on-machines#security"
    And the Assignment queue key names the new corpus
    And the report lists the rewrite counts per rule and a sample of before and after ids
    And timestamps and __typename are unchanged

  Scenario: Reference ids are unchanged
    When I run the site copy with --apply
    Then the Reference id is identical in the target
    And only its discovering monitor id is rewritten

  Scenario: A Reference id that embeds the corpus key stops the copy
    Given a source Reference whose id embeds the corpus key
    When I run the site copy with --apply
    Then the copy is refused and names that Reference
    And the target tables hold no records

  Scenario: An id the tool cannot map is refused
    Given a source Item with an unlisted foreign-key field that embeds the corpus key
    When I run the site copy without --apply
    Then the report refuses it as an id that cannot be mapped

  Scenario: Owners are mapped or reported, never silently dropped
    When I run the site copy with --apply and no owner map
    Then the copy is refused and the unmapped Cognito sub is listed
    When I run the site copy with --apply and an owner map for that sub
    Then the target record carries the new sub
    And service names and emails in owner fields are kept and counted

  Scenario: Media objects are copied and keys that embed the corpus key are renamed
    When I run the site copy with --apply
    Then every source object is in the target bucket
    And the payload key that embedded p-apyr-us carries machines-on-machines

  Scenario: Re-running copies nothing that is already copied
    Given I have run the site copy with --apply
    When I run the site copy with --apply
    Then no record is created or updated and no object is copied
    And a target record edited later is kept and reported, not overwritten

  Scenario: Verify compares counts and content hashes per model
    Given I have run the site copy with --apply
    When I run the site copy with --verify
    Then every model matches on count and content hash
    When a copied record is deleted from the target
    And I run the site copy with --verify
    Then the verification reports it as missing and fails
