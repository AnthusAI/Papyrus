Feature: A site's deploy applies its agent definitions and never moves what a person set
  The agent definitions are files in Git: the core ones in the Papyrus wheel and a site's own, or its additions to a core one, in the site's
  folder of definitions. A site's Amplify build applies them right after it registers the procedures (`papyrus agents apply`), as the build
  role, so the site's backend holds the registered copy of every definition with no step done by hand. Applying checks every definition first
  and stops with a plain error, before anything is written, when one is invalid, names a procedure that is not registered, or would land on an
  automation that is something else. Each definition is the registered copy on an Automation record named for it: the record is created
  disabled when the site has none, and the registered copy follows the rules of agent-definition-registered-copy.feature (the same digest
  writes nothing, a changed digest writes the next version). A definition that is gone from Git is marked retired on its record: the record is
  disabled, it names no schedule, and its registered copy and version stay as its history. Applying never writes the agent policy document, so
  a deploy never sets a rung, a pause or a budget, and never adopts an automation onto a responsibility: a new agent arrives at the rung
  `off` and an admin who is a person adopts it and raises its rung when the time comes. `--dry-run` reads the site and says what would change;
  `--check` reads it and stops when anything differs from Git.

  Scenario: A new definition creates a disabled automation and registers it at version 1
    Given a site with no automations and no agent policy
    When the deploy applies the core definition "rate"
    Then the automation "rate" exists and is disabled
    And the automation "rate" holds the registered definition "rate" at version 1
    And the deploy reports "rate" as new

  Scenario: A new agent arrives at off and the policy document is not written
    Given a site with no automations and no agent policy
    When the deploy applies the core definition "rate"
    Then the policy would not start a run of the responsibility "rate" and says it is off
    And the agent policy document was not written

  Scenario: A deploy of unchanged definitions writes nothing
    Given a site with no automations and no agent policy
    And the deploy has applied the core definition "rate"
    When the deploy applies the core definition "rate"
    Then the deploy wrote nothing
    And the deploy reports "rate" as unchanged

  Scenario: A changed definition becomes the next version
    Given a site with no automations and no agent policy
    And the deploy has applied the core definition "rate"
    When the deploy applies the core definition "rate" with a changed template line
    Then the automation "rate" holds the registered definition "rate" at version 2
    And the deploy reports "rate" as changed
    And the automation "rate" is still disabled

  Scenario: A site's addition to a core definition is a changed version
    Given a site with no automations and no agent policy
    And the deploy has applied the core definition "rate"
    When the deploy applies the core definition "rate" with a site must-never rule
    Then the automation "rate" holds the registered definition "rate" at version 2

  Scenario: A site's own definition is applied beside the core ones
    Given a site with no automations and no agent policy
    And the site folder holds the complete definition "rate-notes" for the responsibility "rate"
    When the deploy applies the core and site definitions
    Then the automation "rate" holds the registered definition "rate" at version 1
    And the automation "rate-notes" holds the registered definition "rate-notes" at version 1
    And the automation "rate-notes" is disabled

  Scenario: A definition removed from Git is retired and its history stays
    Given a site with no automations and no agent policy
    And the site folder holds the complete definition "rate-notes" for the responsibility "rate"
    And the deploy has applied the core and site definitions
    When the site folder no longer holds the definition "rate-notes" and the deploy applies the definitions
    Then the automation "rate-notes" is marked retired
    And the automation "rate-notes" is disabled
    And the automation "rate-notes" still holds the registered definition "rate-notes" at version 1
    And the deploy reports "rate-notes" as retired
    And the automation "rate" is not marked retired

  Scenario: A retired agent has no schedule
    Given a site with no automations and no agent policy
    And the site folder holds the complete definition "rate-notes" for the responsibility "rate"
    And the deploy has applied the core and site definitions
    Then the registered schedules are those of "rate" and "rate-notes"
    When the site folder no longer holds the definition "rate-notes" and the deploy applies the definitions
    Then the registered schedules are those of "rate" alone

  Scenario: Retiring twice writes nothing the second time
    Given a site with no automations and no agent policy
    And the site folder holds the complete definition "rate-notes" for the responsibility "rate"
    And the deploy has applied the core and site definitions
    And the site folder no longer holds the definition "rate-notes" and the deploy has applied the definitions
    When the deploy applies the definitions again
    Then the deploy wrote nothing

  Scenario: A definition that returns to Git is no longer retired
    Given a site with no automations and no agent policy
    And the site folder holds the complete definition "rate-notes" for the responsibility "rate"
    And the deploy has applied the core and site definitions
    And the site folder no longer holds the definition "rate-notes" and the deploy has applied the definitions
    When the site folder holds the complete definition "rate-notes" again and the deploy applies the definitions
    Then the automation "rate-notes" is not marked retired
    And the automation "rate-notes" holds the registered definition "rate-notes" at version 1
    And the automation "rate-notes" is still disabled
    And the deploy reports "rate-notes" as revived

  Scenario: A deploy never changes a rung, a pause or a budget
    Given a site whose agent policy sets the responsibility "rate" to "propose", paused with a reason, and a weekly budget
    When the deploy applies the core definition "rate"
    Then the agent policy document is at the same version with the same rung, pause and budget
    And the agent policy document was not written

  Scenario: A deploy never adopts an automation onto a responsibility
    Given a site with no automations and no agent policy
    When the deploy applies the core definition "rate"
    Then the automation "rate" has no adopted responsibility

  Scenario: An automation a person adopted keeps its responsibility and its switch
    Given a site with the automation "rate" adopted as "rate" and enabled
    When the deploy applies the core definition "rate"
    Then the automation "rate" is adopted as "rate" and is enabled
    And the automation "rate" holds the registered definition "rate" at version 1
    And the deploy reports "rate" as changed

  Scenario: An invalid definition stops the deploy before anything is written
    Given a site with no automations and no agent policy
    And the site folder holds a definition "rate-notes" with no must-never line
    When the deploy applies the core and site definitions
    Then the deploy stops and names the definition "rate-notes" and the line "template.mustNever"
    And the deploy wrote nothing

  Scenario: A definition naming a procedure that is not registered stops the deploy before anything is written
    Given a site with no automations and no agent policy
    And the site folder holds the definition "rate-notes" that runs the procedure "no.such-procedure" for the responsibility "rate"
    When the deploy applies the core and site definitions
    Then the deploy stops and says the procedure "no.such-procedure" of "rate-notes" is not registered
    And the deploy wrote nothing

  Scenario: A procedure the site registers itself is a known procedure
    Given a site with no automations and no agent policy
    And the site folder holds the definition "rate-notes" that runs the procedure "example.site-rating" for the responsibility "rate"
    And the site registers the procedure "example.site-rating"
    When the deploy applies the core and site definitions
    Then the automation "rate-notes" holds the registered definition "rate-notes" at version 1

  Scenario: A definition whose name is another automation's stops the deploy before anything is written
    Given a site with the automation "rate-notes" that runs the procedure "newsroom.editor" and holds no definition
    And the site folder holds the complete definition "rate-notes" for the responsibility "rate"
    When the deploy applies the core and site definitions
    Then the deploy stops and says the automation "rate-notes" runs the procedure "newsroom.editor" and is not an agent the deploy created
    And the deploy wrote nothing

  Scenario: A definition for another responsibility than the one its automation was adopted as stops the deploy
    Given a site with the automation "rate" adopted as "select" and enabled
    When the deploy applies the core definition "rate"
    Then the deploy stops and names the automation "rate"
    And the deploy wrote nothing

  Scenario: A dry run reads the site, says what would change and writes nothing
    Given a site with no automations and no agent policy
    And the site folder holds the complete definition "rate-notes" for the responsibility "rate"
    When the deploy plans the core and site definitions without applying them
    Then the deploy reports "rate" as new
    And the deploy reports "rate-notes" as new
    And the deploy wrote nothing

  Scenario: A drift check passes when every registered copy matches Git
    Given a site with no automations and no agent policy
    And the deploy has applied the core definition "rate"
    When the agent drift check runs
    Then the agent check passes

  Scenario: A drift check fails and names what differs from Git
    Given a site with no automations and no agent policy
    And the site folder holds the complete definition "rate-notes" for the responsibility "rate"
    And the deploy has applied the core and site definitions
    And the site folder no longer holds the definition "rate-notes"
    When the agent drift check runs
    Then the agent check fails and names "rate-notes" as to be retired
    And the deploy wrote nothing
