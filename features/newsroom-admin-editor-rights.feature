Feature: An admin has every editor right
  A site owner is in the admin group and not in the editor group. The newsroom treats admin as editor everywhere:
  the console, the Proposals panel, the reference review card, the editor tier and the newsroom chat. The
  "Editor Role Required" screen appears only to a signed-in account that is in neither group.

  Scenario: An admin without the editor group is staff everywhere
    Given a signed-in account in the admin and Google groups but not the editor group
    When every editor check is asked about that account
    Then the console, the staging gate, the reader staff flag and the newsroom chat identity admit it
    And the groups claim is read the same way whether it arrives as a list, a JSON list or a bracketed string

  Scenario: An admin can review references, use the Proposals panel and the editor tier
    Given a signed-in account in the admin group but not the editor group
    When it files a proposal, moves it, pins it, moderates a reader and imports a reference for review
    Then each action is accepted
    And a reader with neither group is refused the same actions

  Scenario: Only an account with neither group sees Editor Role Required
    Given a signed-in account in the admin group but not the editor group
    When the newsroom backend refuses one of the dashboard reads
    Then the page reports the refused read and does not say the editor role is missing
