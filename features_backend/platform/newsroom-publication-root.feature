Feature: Publication selection for newsroom runtime
  A stored assignment uses its publication configuration and authorized attachment downloads.

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
