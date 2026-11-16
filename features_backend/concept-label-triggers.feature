@backend @multilingual
Feature: A concept is named in a language only when a page in that language needs the name
  A concept's name in another language costs a model call and a check, and most concepts never appear on a page in that language. So the name is made when something
  needs it, and not before: a translated Story is tagged with the concept, the concept's own page is published, or a language is switched on for the site (a bounded
  sweep of the concepts that already have a page or a translated Story). Each trigger asks the one procedure that names a concept (docs/multilingual-labels.md); a
  concept that already has a current, pinned or held label in that language is left alone, so a trigger that fires twice, or from two causes, makes one label.
  (An in-memory site and a scripted model: nothing reaches the network.)

  Scenario: A translated Story tagged with a concept asks for that concept's name in the Story's language
    Given a site whose primary language is "en" and which serves "es-419"
    And the concept "prompt injection" has no "es-419" label
    When a Story in "es-419" is tagged with the concept "prompt injection"
    Then the concept is named in "es-419"
    And no other language is asked for

  Scenario: A Story in the primary language asks for nothing
    Given a site whose primary language is "en" and which serves "es-419"
    When a Story in "en" is tagged with the concept "prompt injection"
    Then no concept is named

  Scenario: A concept that already has a label in the language is not made again
    Given the concept "prompt injection" has a current "es-419" label
    When a Story in "es-419" is tagged with the concept "prompt injection"
    Then the model is asked nothing

  Scenario: A held label is not retried by a trigger
    Given the concept "prompt injection" has a held "es-419" label with an open review request
    When a Story in "es-419" is tagged with the concept "prompt injection"
    Then the model is asked nothing
    And the review request is still the only one
