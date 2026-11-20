@backend @browser-assign-research
Feature: A research assignment made in the newsroom is stored as the command stores it, and the reporting agent reads it
  An editor can assign research from the Story page. The browser writes the same records as papyrus stories assign-research: an Assignment of type research.multi that names the
  Story and its section, the first assignment event, and the editor's direction. The Assignment model has no metadata or instructions column, so the direction and the
  reporter context profile are written to a metadata attachment of the Assignment and the direction text to an instructions attachment. The reporting agent's context
  pack and the research run read the direction through that attachment (PR 1110 was a live bug from writing it as a column). The browser's records are
  recorded by a TypeScript test in features_backend/fixtures/browser-assign-research.json, and these scenarios load that file into the fake newsroom of the
  context pack specs.

  Scenario: The context pack built from what the browser wrote carries the editor's direction
    Given the research assignment as the browser stored it
    When the reporter context pack is built for the Story and that assignment
    Then the pack's user text holds the editor's direction under "Editor's direction (it outranks the Story)"

  Scenario: The direction reaches the pack only through the metadata attachment
    Given the research assignment as the browser stored it, but without its metadata attachment
    When the reporter context pack is built for the Story and that assignment
    Then the pack's user text does not hold the editor's direction

  Scenario: The Assignment row has only columns the model has
    Given the research assignment as the browser stored it
    Then stripping the columns the model lacks changes nothing in the row

  Scenario: The research run accepts the assignment and plans its searches from the direction
    Given the research assignment as the browser stored it
    When the research run is made on it with fake providers and a fake model
    Then the run completed and the model that planned the searches was given the editor's direction

  Scenario: The browser stores what the command stores
    Given the research assignment as the browser stored it
    When the command makes the same research assignment
    Then both have the same Assignment columns, event fields and metadata keys, with the same values
