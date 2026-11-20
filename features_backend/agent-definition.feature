Feature: An agent is one definition file that fills the 11-point template
  An always-on agent is one responsibility on one site. What it is lives in one definition file in Git: the responsibility (from the engine's
  catalog), the procedure key, what wakes it (changes it listens for and an optional schedule with its time zone), what it runs one at a time by,
  whether it is paid and whether it is safe to repeat, each operation it uses with the lowest rung that allows it, its model tier (never a model
  name), and the 11 lines of the template: trigger, inputs, decision, may write, must never, seen and reversed, records, fails, cost and bound,
  measured and Gherkin. A definition that cannot fill a line is refused with the line named. An operation must be one the operation table knows, and
  one an agent may call; the rung it names for an operation may never be lower than the lowest rung the operation table allows an agent to call it at. A definition never sets a
  rung for the agent itself: how far the agent may go is the site's policy, and a deploy never changes it. Core definitions ship in the engine. A site
  may add its own complete definitions, and may extend a core definition with instructions and further must-never rules, but it can never remove a
  must-never rule or change another field of a core definition. papyrus agents validate checks a folder of definitions with no network and no model.

  Scenario: A complete definition validates
    Given a definitions folder with the complete definition "illustrate-stories" for the responsibility "illustrate"
    When the definition folders are validated
    Then the set is accepted with 1 definition
    And the definition "illustrate-stories" lists the operation "image_search" at the lowest rung "observe"

  Scenario Outline: A definition missing a template line is refused with the line named
    Given a definitions folder with the complete definition "illustrate-stories" for the responsibility "illustrate"
    And the definition "illustrate-stories" has no template line "<line>"
    When the definition folders are validated
    Then the set is refused
    And the refusal names the definition "illustrate-stories", the line "template.<line>" and the code "missing_line"

    Examples:
      | line             |
      | trigger          |
      | inputs           |
      | decision         |
      | mayWrite         |
      | mustNever        |
      | seenAndReversed  |
      | records          |
      | fails            |
      | costAndBound     |
      | measured         |
      | gherkin          |

  Scenario: A definition with an empty must-never list is refused
    Given a definitions folder with the complete definition "illustrate-stories" for the responsibility "illustrate"
    And the definition "illustrate-stories" has an empty must-never list
    When the definition folders are validated
    Then the set is refused
    And the refusal names the definition "illustrate-stories", the line "template.mustNever" and the code "empty_line"

  Scenario: An unknown operation is refused
    Given a definitions folder with the complete definition "illustrate-stories" for the responsibility "illustrate"
    And the definition "illustrate-stories" uses the operation "image_teleport" at the rung "draft"
    When the definition folders are validated
    Then the set is refused
    And the refusal names the definition "illustrate-stories", the line "operations.image_teleport" and the code "unknown_operation"

  Scenario: An operation only a person may call is refused
    Given a definitions folder with the complete definition "illustrate-stories" for the responsibility "illustrate"
    And the definition "illustrate-stories" uses the operation "image_review" at the rung "draft"
    When the definition folders are validated
    Then the refusal names the definition "illustrate-stories", the line "operations.image_review" and the code "person_only_operation"

  Scenario: An operation cannot be allowed at a rung below the one the operation table needs
    Given a definitions folder with the complete definition "illustrate-stories" for the responsibility "illustrate"
    And the definition "illustrate-stories" uses the operation "image_apply" at the rung "observe"
    When the definition folders are validated
    Then the refusal names the definition "illustrate-stories", the line "operations.image_apply" and the code "rung_below_table"

  Scenario: An unknown responsibility is refused
    Given a definitions folder with the complete definition "illustrate-stories" for the responsibility "daydream"
    When the definition folders are validated
    Then the refusal names the definition "illustrate-stories", the line "responsibility" and the code "unknown_responsibility"

  Scenario: A definition cannot set a rung for the agent
    Given a definitions folder with the complete definition "illustrate-stories" for the responsibility "illustrate"
    And the definition "illustrate-stories" sets the rung "publish_auto"
    When the definition folders are validated
    Then the refusal names the definition "illustrate-stories", the line "rung" and the code "policy_field"

  Scenario Outline: A definition's own fields are checked
    Given a definitions folder with the complete definition "illustrate-stories" for the responsibility "illustrate"
    And the definition "illustrate-stories" has <problem>
    When the definition folders are validated
    Then the refusal names the definition "illustrate-stories", the line "<line>" and the code "<code>"

    Examples:
      | problem                                   | line             | code          |
      | the tier "gpt-6-luna"                     | tier             | invalid_value |
      | the executor "container"                  | executor         | invalid_value |
      | no wake at all                            | wakes            | missing_line  |
      | a schedule with the time zone "Mars/Base" | wakes.schedule   | invalid_value |
      | a schedule that is not a cron expression  | wakes.schedule   | invalid_value |
      | the serial scope "everything"             | serialBy         | invalid_value |
      | no paid flag                              | paid             | missing_line  |
      | no safe-to-repeat flag                    | safeToRepeat     | missing_line  |
      | no procedure key                          | procedure        | missing_line  |
      | an unknown field "mood"                   | mood             | unknown_key   |
      | a listen for a change no feed produces    | wakes.changes[0] | unknown_change |
      | a listen for a change of a kind no feed covers | wakes.changes[0] | unknown_change |

  Scenario Outline: A definition may listen for each change the change feeds produce
    Given a definitions folder with the complete definition "illustrate-stories" for the responsibility "illustrate"
    And the definition "illustrate-stories" listens for the change "<change>" of "<kind>"
    When the definition folders are validated
    Then the set is accepted

    Examples:
      | kind                | change          |
      | Item                | version_created |
      | Item                | stage_entered   |
      | Item                | step_changed    |
      | Reference           | created         |
      | Reference           | accepted        |
      | Reference           | rated           |
      | Reference           | recaptured      |
      | ReviewRequest       | answered        |
      | Message             | posted          |
      | LocalizationRequest | wanted          |
      | Delivery            | state_changed   |

  Scenario: The knowledge responsibility may run as a container
    Given a definitions folder with the complete definition "weekly-knowledge-run" for the responsibility "knowledge"
    And the definition "weekly-knowledge-run" runs as a container
    When the definition folders are validated
    Then the set is accepted with 1 definition

  Scenario: Two definitions with one id, and a file named for another id, are refused
    Given a definitions folder with the complete definition "illustrate-stories" for the responsibility "illustrate"
    And the definition file "copy-of-it" holds the id "illustrate-stories"
    When the definition folders are validated
    Then the refusal names the definition "copy-of-it", the line "id" and the code "invalid_value"

  Scenario: A site addition of instructions and a must-never rule is accepted
    Given the engine's core definition "illustrate-stories" for the responsibility "illustrate"
    And a site definitions folder that extends "illustrate-stories" with the instruction "Prefer photographs of real places" and the must-never rule "Use a stock image of a person's face"
    When the definition folders are validated
    Then the set is accepted with 1 definition
    And the effective definition "illustrate-stories" keeps every core must-never rule
    And the effective definition "illustrate-stories" also has the must-never rule "Use a stock image of a person's face"
    And the effective definition "illustrate-stories" also has the instruction "Prefer photographs of real places"

  Scenario: A site cannot remove a must-never rule of a core definition
    Given the engine's core definition "illustrate-stories" for the responsibility "illustrate"
    And a site definitions folder that extends "illustrate-stories" and removes the core must-never rule "Add a credit to a generated image"
    When the definition folders are validated
    Then the set is refused
    And the refusal names the definition "illustrate-stories", the line "removes" and the code "base_rule_removed"

  Scenario: A site cannot change any other field of a core definition
    Given the engine's core definition "illustrate-stories" for the responsibility "illustrate"
    And a site definitions folder that extends "illustrate-stories" and sets the tier "bulk"
    When the definition folders are validated
    Then the refusal names the definition "illustrate-stories", the line "tier" and the code "not_addable"

  Scenario: A site extension of a definition the engine does not have is refused
    Given a site definitions folder that extends "no-such-agent" with the instruction "Be brief"
    When the definition folders are validated
    Then the refusal names the definition "no-such-agent", the line "extends" and the code "unknown_base"

  Scenario: A site may add its own complete definition, but not reuse a core id
    Given the engine's core definition "illustrate-stories" for the responsibility "illustrate"
    And a site definitions folder with the complete definition "site-newsletter" for the responsibility "newsletter"
    And the site folder also has the complete definition "illustrate-stories" for the responsibility "illustrate"
    When the definition folders are validated
    Then the refusal names the definition "illustrate-stories", the line "id" and the code "duplicate_id"
    And the definition "site-newsletter" is not among the refusals

  Scenario: papyrus agents validate checks a folder offline
    Given a definitions folder with the complete definition "illustrate-stories" for the responsibility "illustrate"
    When papyrus agents validate is run on the folder with the network closed
    Then the command exits with status 0
    And the answer lists the definition "illustrate-stories"

  Scenario: papyrus agents validate exits with 2 and names every problem when the folder is refused
    Given a definitions folder with the complete definition "illustrate-stories" for the responsibility "illustrate"
    And the definition "illustrate-stories" has no template line "mustNever"
    When papyrus agents validate is run on the folder with the network closed
    Then the command exits with status 2
    And the answer names the definition "illustrate-stories", the line "template.mustNever" and the code "missing_line"

  Scenario: The engine's own core definitions are valid
    When the engine's core definitions are validated
    Then the set is accepted
