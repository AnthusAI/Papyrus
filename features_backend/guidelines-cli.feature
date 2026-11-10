Feature: papyrus guidelines reads and saves any kind of guidelines from the command line
  papyrus guidelines show, resolve, diff, save and history work for every registered kind of guidelines (writing, image, video and any added later), for the
  site or one section. They are generated from the same operation table as the door and the MCP tools, so a flag, a tool and a TypeScript type cannot
  disagree. A signed-in person uses their own session and the backend applies their rights. save writes unless --dry-run; a dry run prints what would change
  and stores nothing. diff and a dry run never save. --help is answered from the table and sends nothing. The tests use an in-memory backend.

  Scenario: papyrus guidelines save writes unless --dry-run
    Given a command line onto a publication with saved writing guidelines
    When an admin runs save with a changed audience and --dry-run
    Then the answer is a dry run that previews the audience change and nothing new is stored
    When the admin runs the same save without --dry-run
    Then the writing guidelines are at version 2 and say the audience is "Engineers"

  Scenario: papyrus guidelines diff shows the change and saves nothing
    Given a command line onto a publication with saved writing guidelines
    When an admin runs diff with a changed tone and a removed binding constraint
    Then the answer lists the tone change and the removed constraint
    And no new guideline version is stored

  Scenario: papyrus guidelines resolve prints each field with where it came from
    Given a command line onto a publication with saved writing guidelines
    And a section "security" with its own tone and audience
    When an admin runs resolve for the section "security"
    Then every field in the answer names the layer it came from
    And the answer names both layers with their versions

  Scenario: show prints the version to pass to the next save
    Given a command line onto a publication with saved writing guidelines
    When an admin runs show for the writing guidelines
    Then the answer holds the document and the version id to pass as the version being replaced
    When an admin runs show for the video guidelines
    Then the answer says there are none and that the first save passes "none"

  Scenario: An editor cannot save and an agent cannot change a binding constraint
    Given a command line onto a publication with saved writing guidelines
    When an editor runs save
    Then the command fails because the caller is not authorised
    When an agent in an admin's session runs save dropping the binding constraint
    Then the command fails because a person is required and nothing new is stored

  Scenario: The commands are generated from the one operation table
    Then the guideline commands, the MCP tools and the TypeScript types list the same five operations in the same order
    And the generated files are current
    And the CLI and the MCP tool print identical JSON for each guideline operation

  Scenario: papyrus guidelines --help sends nothing
    When an agent runs "papyrus guidelines save --help" with no site and no sign-in
    Then the printed usage shows "--dry-run" and says the command writes by default
    And no connection to a site was opened
