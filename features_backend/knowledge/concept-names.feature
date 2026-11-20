@backend @multilingual
Feature: A concept is found by its name with one index query
  A concept keeps one identity and one set of edges. Each name it has (its name, its other names and the hashtag of its key) is a label row in the language
  the concept is written in, written by the one consumer of the concept table's change stream. Tagging, the section commands and the console links find a
  concept by looking a name up in that index, never by reading the whole concept table. A concept that has no language is given the site's primary
  language, written explicitly. (docs/multilingual-labels.md; an in-memory site that counts every whole-table read.)

  Background:
    Given a site that writes in "en"
    And the concept "Human oversight" with the other name "human control" and the hashtag "human-oversight"
    And the concept "Automation bias"

  Scenario: A concept's names become rows and the concept gets its language
    When the concept names are synchronised
    Then the concept "Human oversight" has the language "en"
    And its names are "Human oversight", "human control" and "human-oversight"
    And a second synchronisation writes nothing

  Scenario: A name is found however it is typed, without reading the concept table
    Given the concept names are synchronised
    When an editor looks up "HUMAN control", "#human-oversight" and "editor_concept--human-oversight"
    Then each finds "Human oversight"
    And the concept table was not listed

  Scenario: A renamed concept moves its rows
    Given the concept names are synchronised
    When the concept "Human oversight" is renamed "Human supervision" and loses its other name
    And the concept names are synchronised
    Then looking up "human control" finds nothing
    And looking up "human supervision" finds "Human supervision"

  Scenario: A translated name is made stale when the words it came from change
    Given the concept names are synchronised
    And the concept "Human oversight" has a machine-made "es-419" name "Supervisión humana" made from its current words
    When the description of "Human oversight" changes
    And the concept names are synchronised
    Then the "es-419" name of "Human oversight" is stale and appears in the work list of "es-419"

  Scenario: A person's wording is in conflict, not stale, when the words change
    Given the concept names are synchronised
    And the concept "Human oversight" has a pinned "zh-Hans" name "人类监督" made from its current words
    When the description of "Human oversight" changes
    And the concept names are synchronised
    Then the "zh-Hans" name of "Human oversight" is in conflict and the wording is unchanged

  Scenario: A concept and a section with one name do not collide
    Then the name key of the concept "Safety" differs from the name key of the section "Safety"

  Scenario: The backfill gives every existing concept its names and can be run again
    When the backfill is dry run
    Then it reports 2 concepts to change and writes nothing
    When the backfill is applied
    And the backfill is applied again
    Then the second run created nothing
