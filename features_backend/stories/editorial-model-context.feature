Feature: The publication's stored guidance reaches every model request
  A request to a model carries the publication's current guidance from the database, alongside the criteria learned from editors
  and the copy-edit controls. It carries only the guidance of the section the request is for, a request prepared before the policy
  changed is refused before it is sent, and a call that names no model uses the one standard model.

  Scenario: A classification request inherits only the guidance of its section
    Given current synthetic publication doctrine and two independent sections
    When a classification request is prepared for the science section
    Then its request contains publication and science policy without business policy

  Scenario: A changed database policy replaces stale request context
    Given current synthetic publication doctrine and two independent sections
    When a classification request is prepared for the science section
    And the current publication policy is updated in the database
    Then the old prepared request is refused before model transmission
    And a fresh request contains the updated policy and a different context identity

  # Papyrus has one standard model. An editor or operator who does not choose a model gets GPT-6 Luna, so cost estimates,
  # run records and review all name the same model.
  Scenario: A call with no model chosen uses gpt-6-luna
    When a model request is made without choosing a model
    Then the model used for the reference filter, the reference summary, the editorial rewrite and the general and small roles is "gpt-6-luna"
    And the reader extraction setup asks "gpt-6-luna"
