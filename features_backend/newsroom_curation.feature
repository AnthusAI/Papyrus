Feature: Account-scoped reference curation in Papyrus
  Scenario Outline: Curate from either supported transport
    Given an authorized publication workspace using <mode> execution
    When the editor opens References
    Then shared monitoring, human review and authorized proposal controls are available
    And optional example priming accepts a source URL without manual source fields
    And a label and explanation must be chosen before accepting the example
    Examples:
      | mode     |
      | embedded |
      | remote   |

  Scenario: Account selection changes while a request waits
    Given a request pinned to a verified person, account, publication and binding
    When the original session loses access or changes scope before ownership
    Then the operation is refused before protected reads or writes
    And the UI discards the old snapshot and draft state

  Scenario: An unconfigured publication uses the released CMS
    Given no curation host has been configured
    When the editor opens References
    Then the existing reference workflows remain available
    And no curation backend is activated automatically
