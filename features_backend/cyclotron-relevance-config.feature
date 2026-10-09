Feature: Relevance cyclotron configuration
  One installation is one publication, and it configures one relevance
  cyclotron: the decision whether a candidate source should become a
  reference. Doctrine seeds the first rubric, never the question.

  Scenario: A publication configures its relevance cyclotron
    Given a steering config with a relevance cyclotron block
    And the publication doctrine
    When the worker builds the relevance cyclotron
    Then the cyclotron asks one yes-or-no question with include as the yes
    And the question does not contain the doctrine
    And the first rubric is the publication doctrine
    And decisions use Jev and the LLM optimizer uses OpenAI

  Scenario: Editing doctrine keeps the cyclotron definition
    Given a steering config with a relevance cyclotron block
    And the publication doctrine
    When the worker builds the relevance cyclotron
    And the publication doctrine changes
    And the worker builds the relevance cyclotron again
    Then the cyclotron definition is unchanged
    And the first rubric follows the new doctrine

  Scenario: An invalid block is refused with the field named
    Given a steering config whose relevance cyclotron positive label is not one of its labels
    When the steering config is loaded
    Then loading fails naming "relevanceCyclotron.positiveLabel"

  Scenario: Provider keys never come from the config
    Given a steering config whose relevance cyclotron block contains an apiKey
    When the steering config is loaded
    Then loading fails saying keys come from the environment

  Scenario: Without a block there is no relevance cyclotron
    Given a steering config without a relevance cyclotron block
    When the steering config is loaded
    Then the publication has no relevance cyclotron
