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

  Scenario: A need is recorded as one row in the work list, and recording it again writes nothing
    Given a site whose primary language is "en" and which serves "es-419"
    When a page in "es-419" needs the concept "prompt injection" twice
    Then the work list of "es-419" holds one wanted row for "prompt injection"
    And no name has been written

  Scenario: A concept that already has a label in the language is never recorded as wanted
    Given the concept "prompt injection" has a held "es-419" label with an open review request
    When a page in "es-419" needs the concept "prompt injection" twice
    Then the work list of "es-419" holds no wanted row

  Scenario: Draining names what is wanted and clears the queue
    Given a site whose primary language is "en" and which serves "es-419"
    And pages in "es-419" need the concepts "prompt injection" and "gradient descent"
    When the wanted concept names are drained
    Then both concepts are named in "es-419"
    And the work list of "es-419" holds no wanted row
    And draining again asks the model nothing

  Scenario: The ceiling stops the drain and a second run goes on
    Given a site whose primary language is "en" and which serves "es-419"
    And pages in "es-419" need the concepts "prompt injection", "gradient descent" and "data poisoning"
    When the wanted concept names are drained with a ceiling of 0.01 dollars and each name costs 0.02
    Then one concept is named and the drain says it stopped
    And two wanted rows remain
    When the wanted concept names are drained
    Then all three concepts are named in "es-419"

  Scenario: A wanted row whose concept was named meanwhile is dropped without asking
    Given a site whose primary language is "en" and which serves "es-419"
    And pages in "es-419" need the concepts "prompt injection"
    And the concept "prompt injection" is named in "es-419" by a person
    When the wanted concept names are drained
    Then the model is asked nothing
    And the work list of "es-419" holds no wanted row

  Scenario: Publishing a translation or tagging an original records the need and names nothing
    Given an English Story tagged with "prompt injection" that has a published translation in "es-419"
    When the translation is published and then the Story is tagged again with "prompt injection"
    Then the work list of "es-419" holds one wanted row for "prompt injection"
    And no name has been written

  Scenario: Publishing a concept's page notes that its name is needed in every language the site serves
    Given a site whose primary language is "en" and which serves "es-419"
    When the page of the concept "prompt injection" is published
    Then the work list of "es-419" holds one wanted row for "prompt injection"
    And no name has been written

  Scenario: A page that is no accepted concept's notes nothing
    Given a site whose primary language is "en" and which serves "es-419"
    When the page of the concept "bicycle" is published
    Then the work list of "es-419" holds no wanted row

  Scenario: Switching a language on marks only the concepts that have a public page, and a second run adds nothing
    Given a site whose primary language is "en" and which serves "es-419"
    And the concepts "prompt injection" (with a page) and "bicycle" (without one) exist
    When "es-419" is swept
    Then the work list of "es-419" holds one wanted row for "prompt injection"
    And sweeping "es-419" again records nothing
