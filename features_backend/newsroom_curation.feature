@requires-cyclotron
Feature: Account-scoped reference curation in Papyrus
  Scenario Outline: Curate from either supported transport
    Given an authorized publication workspace using <mode> execution
    When the editor opens References
    Then shared monitoring, human review and authorized proposal controls are available
    And optional example priming accepts a source URL without manual source fields
    And a label must be chosen before accepting the example
    And a classification explanation is optional
    Examples:
      | mode     |
      | embedded |
      | remote   |

  Scenario: Account selection changes while a request waits
    Given a request pinned to a verified person, account, publication and binding
    When the original session loses access or changes scope before ownership
    Then the operation is refused before protected reads or writes
    And the UI discards the old snapshot and draft state

  Scenario: The Papyrus routes pass only what the person's role allows to the curation peer
    Given a central curation peer for the publication
    When a member and a viewer of the account open References through the Papyrus routes
    Then the routes pass monitoring and a source URL preview to the peer for the member
    And the viewer can read monitoring but cannot start an import
    And the peer never receives the viewer's import

  Scenario: An unconfigured publication uses the released CMS
    Given no curation host has been configured
    When the editor opens References
    Then the existing reference workflows remain available
    And no curation backend is activated automatically

  @requires-cyclotron
  Scenario Outline: Leaving an import preview saves nothing
    Given a References workspace that prepares web pages offline using <mode> execution
    When the editor previews a reference from a web address
    And the editor <leaves>
    Then no reference has been added
    And a draft that was left cannot be saved afterwards
    Examples:
      | mode     | leaves                                      |
      | embedded | cancels the import                          |
      | remote   | cancels the import                          |
      | embedded | rejects the preview and asks for a revision |
      | remote   | rejects the preview and asks for a revision |

  @requires-cyclotron
  Scenario Outline: A web page preview shows everything used to make suggestions
    Given a References workspace that prepares web pages offline using <mode> execution
    When the editor previews a reference from a web address
    Then the preview lists the exact details used to make suggestions
    And the preview keeps where the page came from and how it was prepared
    And no reference has been added
    Examples:
      | mode     |
      | embedded |
      | remote   |
