Feature: The newsroom runtime reads an Assignment's stored text through its publication
  An Assignment's brief and instructions are stored as attachments. The newsroom runtime reads them using the configuration of the
  publication it was pointed at and an authorized download, with no direct permission on the storage. A download that is denied is
  reported as that error and never passed off as an Assignment with no guidance.

  Scenario: Hydrate stored text without direct storage permission
    Given an explicit publication root containing storage configuration
    When the newsroom runtime reads the stored assignment brief and instructions
    Then the selected publication text is returned
    And the configured knowledge work directory is preserved

  Scenario: A denied download must not appear as missing guidance
    Given an explicit publication root containing storage configuration
    And the assignment attachment download is denied
    When the newsroom runtime reads the stored assignment brief and instructions
    Then the assignment context read fails with the download error
