Feature: A backend that lacks a model is an error, not a reason to skip the work
  The operator commands used to treat an undefined list field as "that model is not deployed yet" and carried on: records of an
  optional model were dropped from an import, an export was written empty, a reset skipped a model, and an orphan check counted every
  owner of a missing kind as gone. Every one of those hid a backend that was not deployed behind output that looked successful. The
  fix for a missing model is to deploy it, so the commands now stop with the backend's own error. These scenarios run the real
  functions against a stand-in for the GraphQL client.

  Scenario: Finding the owners of attachments stops when the owner model is undefined
    Given a backend that does not define the Reference model
    When the owners of Reference attachments are looked up
    Then the lookup stops with the backend's FieldUndefined error

  Scenario: Importing lexical steering rules stops when the rule model is undefined
    Given a backend that does not define the LexicalSteeringRule model
    When the lexical steering configuration is applied
    Then the import stops with the backend's FieldUndefined error

  Scenario: Exporting lexical steering rules stops when the rule model is undefined
    Given a backend that does not define the LexicalSteeringRule model
    When the lexical steering rules are exported
    Then the export stops with the backend's FieldUndefined error and no export file is written

  Scenario: The record helpers keep no list of models that may be missing
    Then the records module keeps no optional-model tolerance
