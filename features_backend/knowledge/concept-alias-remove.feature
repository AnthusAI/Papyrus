@backend
Feature: An alias can be taken off a concept
  An alias is another name a concept answers to. `knowledge entities alias --key K --remove NAME` takes one off the way `--add` puts one on: the same actors, the
  same record of who changed it, one change to the concept. The concept's own name is not an alias, so it is refused, and a name the concept does not hold changes
  nothing. (The concept's name rows follow from the concept by themselves; docs/multilingual-labels.md.)

  Scenario: An alias is removed and who removed it is recorded
    Given a concept "continuous integration" with the aliases "CI" and "continuous integration (check)"
    When the actor "ai" removes the alias "continuous integration (check)"
    Then the concept's aliases are "CI"
    And the change is recorded as made by "ai"

  Scenario: The name is matched without regard to case or spacing
    Given a concept "continuous integration" with the aliases "CI" and "continuous integration (check)"
    When the actor "human" removes the alias "  Continuous  Integration (CHECK) "
    Then the concept's aliases are "CI"

  Scenario: A name the concept does not hold changes nothing
    Given a concept "continuous integration" with the aliases "CI"
    When the actor "ai" removes the alias "Jenkins"
    Then nothing is changed

  Scenario: The concept's own name is not an alias
    Given a concept "continuous integration" with the aliases "CI"
    When the actor "ai" removes the alias "continuous integration"
    Then it is refused saying the name is not an alias and the concept is to be renamed
