Feature: Knowledge beat styling and knowledge directory precedence
  The standard front end ships a default knowledge stylesheet, and a build can read the knowledge snapshot
  from a local directory instead of the site store. Two details must hold. First, the beat parts, the
  trend line with its two count readouts and the list of top-entity chips, are laid out by the stylesheet
  rather than left to browser defaults, using only the theme tokens the stylesheet already documents.
  Second, choosing a local knowledge directory always wins over the site store, whether the choice is made
  before or after the projection context is built, so code that drives the engine directly does not need
  to know the order.

  Scenario: The beat trend readouts are separated by a gap
    Given the default knowledge stylesheet
    Then the "papyrus-knowledge-beat-trend" rule lays its children out in a wrapping flex row with a gap

  Scenario: The beat entities list has no bullets or padding
    Given the default knowledge stylesheet
    Then the "papyrus-knowledge-beat-entities" rule removes the list bullets and the padding

  Scenario: The beat rules use only theme tokens
    Given the default knowledge stylesheet
    Then the beat rules use only "--papyrus-knowledge-" custom properties and no literal colours

  Scenario: A knowledge directory set before the context is built is kept
    Given a knowledge source with a store attached
    When the knowledge directory is chosen and then the store is attached
    Then the snapshot is read from the directory

  Scenario: A knowledge directory set after the context is built is kept
    Given a knowledge source with a store attached
    When the store is attached and then the knowledge directory is chosen
    Then the snapshot is read from the directory
