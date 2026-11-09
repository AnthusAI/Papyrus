Feature: A generated image has no credit line
  Agents write a credit on pictures they add to a Story, and when the picture is one a model made they have worded it many ways: "Illustration
  generated with AI", "Illustration drafted by AI.", "Drafted by AI." and others. Ryan's rule is that a generated image gets no credit at all, not
  even "Generated": it is obvious that we generated it. Every credit that only says a machine made the picture is therefore dropped, on the page and in
  the Markdown copy of the Story, whatever the agent wrote, and the caption (if any) stands alone. A real credit to a person, a photographer or a
  source is never touched, because it is the credit the rights holder asked for. The four-lens review treats a picture with such a credit as ours, so it
  needs no credit, while a third-party picture with no credit is still blocked and a local picture with no record stays unassessable. Agents are told the rule in their context pack.

  Scenario Outline: A credit that only says a machine made the picture is not shown on the page
    Given a Story picture credited "<written>"
    When the picture is rendered on the page
    Then there is no credit under the picture

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
      | Generated                      |

  Scenario: A figure with a caption and a machine credit shows only the caption
    Given a Story picture with the caption "The harbour at dusk" credited "Illustration generated with AI"
    When the picture is rendered on the page
    Then the figure caption is exactly "The harbour at dusk"
    And there is no credit under the picture

  Scenario Outline: The Markdown copy of the Story has no credit on that picture
    Given a Story picture credited "<written>"
    When the Markdown copy of the Story is made
    Then the picture in the Markdown copy has no credit

    Examples:
      | written                        |
      | Illustration generated with AI |
      | Illustration drafted by AI.    |
      | Drafted by AI.                 |
      | Generated                      |

  Scenario: The Markdown copy of a home page has no credit on that picture
    Given a Story picture credited "Illustration generated with AI"
    When the Markdown copy of the home page is made
    Then the picture in the Markdown copy has no credit

  Scenario: A picture written over several lines keeps a valid directive when its machine credit is dropped
    Given a Story picture written over several lines with the credit "Drafted by AI."
    When the Markdown copy of the Story is made
    Then the picture in the Markdown copy has no credit
    And the Markdown copy still has the picture's source and alt text

  Scenario Outline: A real third-party credit is not touched
    Given a Story picture credited "<credit>"
    When the picture is rendered on the page
    Then the credit under the picture is "<credit>"
    When the Markdown copy of the Story is made
    Then the picture in the Markdown copy is credited "<credit>"

    Examples:
      | credit                                                                   |
      | Image: U.S. Air Force / Trevor Cokley, Public domain via Wikimedia Commons |
      | colsto                                                                   |

  Scenario: A generated picture with a machine credit needs no credit for the third-party credit check
    Given a Story with this body
      """
      ::image{src="https://images.example.test/generated.png" alt="A harbour at dusk" credit="Illustration drafted by AI."}
      """
    When the lens checks run
    Then the finding "P10" is a "pass"
    And the finding "C6" is a "pass"

  Scenario: A generated picture in our own media with a machine credit passes the third-party credit check
    Given a Story with this body
      """
      ::image{src="assets/harbour.png" alt="A harbour at dusk" credit="Generated"}
      """
    When the lens checks run
    Then the finding "P10" is a "pass"
    And the finding "C6" is a "pass"

  Scenario: A local picture with no credit and no record is not assumed to be ours
    Given a Story with this body
      """
      ::image{src="assets/harbour.png" alt="A harbour at dusk"}
      """
    When the lens checks run
    Then the finding "P10" is a "not_assessable"

  Scenario: A third-party picture with no credit is still blocked
    Given a Story with this body
      """
      ::image{src="https://photos.example.test/harbour.jpg" alt="A harbour at dusk"}
      """
    When the lens checks run
    Then the finding "P10" is a "problem"
    And the finding "C6" is a "problem"
    And "P10" is among the problems that block a lens step
