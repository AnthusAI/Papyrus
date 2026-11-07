Feature: One table of image operations that every front end is generated from
  Everything a person or an agent can do with a picture for a Story (read or change the publication's style profile, plan, search for stock, generate,
  read a round, retry, iterate, select, review, apply, undo and discard) is one named operation in one table, src/papyrus_content/images/operations.py.
  Each operation says its tool name, its command, what it takes and returns, which errors it can give, who may call it and what it does in plain words.
  The papyrus images commands, the MCP tool schema, the newsroom's TypeScript types, the reference block in the image-work skill and docs/images.md are all
  generated from that table by one script, so an agent reading the skill, a person using the command and the newsroom calling the service cannot disagree.
  Both the command and the MCP tool only turn what they are given into the operation's input and pass it to the same function, which checks who is asking
  and whether the input fits and then calls the operation's handler. This first step builds the table, the generators and the checks. Every handler
  still answers that it is not built yet, and nothing here calls a model, an image provider or AWS.

  Scenario: The generated files are exactly what the table produces
    Then the generated command spec, MCP schema, TypeScript types, skill reference block and docs are all current
    And the generator's check mode reports nothing out of date

  Scenario: Each front end covers exactly the operations in the table
    Then the command spec, the MCP tool schema, the TypeScript types, the skill block and the docs each list the same operations as the table, in the same order
    And the table has the 24 operations the design describes
    And the generate operation offers a speed of auto, standard or batch

  Scenario Outline: The command and the MCP tool give identical JSON for the same request
    Given a backend that answers <operation> with its documented example
    When the example input for <operation> is given as a command line
    And the same input is sent as the MCP tool <operation>
    Then both answer with the same JSON
    And that JSON is a success from the backend's publication carrying the documented example result

    Examples:
      | operation                    |
      | image_profile_get            |
      | image_profile_resolve        |
      | image_profile_diff           |
      | image_profile_save           |
      | image_profile_history        |
      | image_profile_example_add    |
      | image_profile_example_remove |
      | image_capabilities           |
      | image_brief_draft            |
      | image_prompt_preview         |
      | image_search                 |
      | image_generate               |
      | image_figure_add             |
      | image_round_get              |
      | image_candidate_get          |
      | image_list                   |
      | image_retry                  |
      | image_iterate                |
      | image_select                 |
      | image_unapply                |
      | image_review                 |
      | image_review_queue           |
      | image_apply                  |
      | image_discard                |

  Scenario: An agent may not call an operation that needs a person
    Given a backend that would answer image_review
    When an agent runs the command "review media-asset-1 --decision keep"
    And an agent calls the MCP tool image_review for media-asset-1 with the decision keep
    Then both answer that a person is required
    And the backend was never called
    And the command exits with the error code

  Scenario: A person may call it
    Given a backend that would answer image_review
    When a person runs the command "review media-asset-1 --decision keep"
    Then the command succeeds and the backend was called once

  Scenario: An operation that does not exist is an error, not a crash
    When the MCP tool image_paint is called
    And a person runs the command "paint everything"
    Then both answer that the operation is unknown
    And the command exits with the error code

  Scenario: Input that does not fit is refused and names the field
    When a person runs the command "generate --story story-1 --use banner --brief x"
    And the MCP tool image_generate is called with the use banner
    Then both answer that the input is invalid, naming the field "use"
    And the answers are identical

  Scenario: A bad image type is refused the same way by the command and the MCP tool
    When a person runs the command "generate --story story-1 --use cover --brief x --image-type="
    And the MCP tool image_generate is called with an empty image type
    Then both answer that the input is invalid, naming the field "imageType"
    And the answers are identical

  Scenario: Adding a figure needs an image type
    When the MCP tool image_figure_add is called without an image type
    Then it answers that the input is invalid, naming the field "imageType"

  Scenario: The image type errors are shared and named by the operations that can give them
    Then image_type_required, image_type_unknown and source_not_allowed are in the shared error table
    And image_figure_add names image_type_unknown, source_not_allowed, checks_failed and not_found

  Scenario: A request for a property the operation does not have is refused
    When the MCP tool image_round_get is called with an extra property "extra"
    Then it answers that the input is invalid, naming the field "extra"

  Scenario: Until its build step, every operation says it is not built yet
    When every operation is run with its example input and the default handlers
    Then each answers not_implemented and names its operation
    And the command exits with the error code
