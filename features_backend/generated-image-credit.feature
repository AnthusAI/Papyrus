Feature: A generated image's credit is exactly "Generated"
  Agents write a credit on every picture they add to a Story, and when the picture is one a model made they have worded it many ways: "Illustration
  generated with AI", "Illustration drafted by AI.", "Drafted by AI." and others. Ryan's rule is that the credit on any generated image says simply
  "Generated". Every credit that only says a machine made the picture is therefore shown as "Generated", on the page and in the Markdown copy of the
  Story, whatever the agent wrote. A real credit to a person, a photographer or a source is never touched, because it is the credit the rights holder
  asked for. The four-lens review accepts "Generated" as the credit for our own picture, and agents are told the rule in their context pack.

  Scenario Outline: Every wording that only says a machine made the picture is shown as "Generated" on the page
    Given a Story picture credited "<written>"
    When the picture is rendered on the page
    Then the credit under the picture is "Generated"

    Examples:
      | written                        |
      | Illustration generated with AI |
      | Illustration drafted by AI.    |
      | Drafted by AI.                 |
      | AI-generated                   |
      | AI generated                   |
      | Image created by an AI         |
      | Art rendered with a model      |
      | generated                      |

  Scenario Outline: The Markdown copy of the Story says "Generated" too
    Given a Story picture credited "<written>"
    When the Markdown copy of the Story is made
    Then the picture in the Markdown copy is credited "Generated"

    Examples:
      | written                        |
      | Illustration generated with AI |
      | Illustration drafted by AI.    |
      | Drafted by AI.                 |

  Scenario: The Markdown copy of a home page says "Generated" too
    Given a Story picture credited "Illustration generated with AI"
    When the Markdown copy of the home page is made
    Then the picture in the Markdown copy is credited "Generated"

  Scenario: A real third-party credit is not touched
    Given a Story picture credited "Image: U.S. Air Force / Trevor Cokley, Public domain via Wikimedia Commons"
    When the picture is rendered on the page
    Then the credit under the picture is "Image: U.S. Air Force / Trevor Cokley, Public domain via Wikimedia Commons"
    When the Markdown copy of the Story is made
    Then the picture in the Markdown copy is credited "Image: U.S. Air Force / Trevor Cokley, Public domain via Wikimedia Commons"

  Scenario: A generated picture credited "Generated" satisfies the third-party credit check
    Given a Story with this body
      """
      ::image{src="https://images.example.test/generated.png" alt="A harbour at dusk" credit="Illustration drafted by AI."}
      """
    When the lens checks run
    Then the finding "P10" is a "pass"
    And the finding "C6" is a "pass"
