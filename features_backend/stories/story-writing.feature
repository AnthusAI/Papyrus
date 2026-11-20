Feature: An editor's outline and a copywriter's draft come from the standard context packs
  Once research is done an editor agent writes the outline: what the Story claims, in what order, which sources carry it and what is still thin. A copywriter
  then writes the draft from that outline. Each is one model call from the pack that agent always gets, saved as a new version of the Story, so nothing earlier
  is lost. Neither publishes. A draft may only cite the Story's own References by the keys it was given, because that is the part that can be checked without a
  model: a draft that cites anything else, or nothing at all when it could, is refused and nothing is saved. Whether its claims are true of their sources is the
  fact check that follows. A missing earlier step warns and does not stop the work. Nothing here calls a model or a network: the model is a stand-in.

  Background:
    Given a Story with research and two attached References, one of them rejected by an editor

  Scenario: The editor's outline uses the editor's pack and is saved as the outline
    Given the model answers with an outline, saying the research is thin in one place
    When the outline is written
    Then the model was given the editor's role and the Story's research
    And a new version is saved with the outline as its body and the thin place under "Still thin"
    And that version is marked as the outline
    And the change reason says it is by AI and names the pack it came from
    And the Story's stage did not change

  Scenario: A dry run of the outline saves nothing
    Given the model answers with an outline, saying the research is thin in one place
    When the outline is written as a dry run
    Then no version is saved
    And the result still holds the outline

  Scenario: The copywriter's draft uses the copywriter's pack and only the Story's References
    Given the model answers with a draft citing the accepted Reference
    When the draft is written
    Then the model was given the copywriter's role and the citation key of the accepted Reference
    And the model was not given a citation key for the rejected Reference
    And a new version is saved with the draft as its body and the bibliography at its end
    And its front matter holds the title, deck, blurb and the citation of the accepted Reference
    And the cited Reference is marked as cited with its key
    And the Story moves to copywriting

  Scenario: A draft that cites a key it was not given is refused
    Given the model answers with a draft citing a key that does not exist
    When the draft is written
    Then the draft is refused naming the key
    And no version is saved

  Scenario: A draft that cites nothing is refused when the Story has References
    Given the model answers with a draft that cites nothing
    When the draft is written
    Then the draft is refused saying it cites nothing
    And no version is saved

  Scenario: What the copywriter could not support goes to the editor
    Given the model answers with a draft citing the accepted Reference and one evidence gap
    When the draft is written
    Then the result lists the evidence gap
    And the change reason holds the evidence gap

  Scenario: A key stays the same on the next draft
    When the citation keys are read twice
    Then they are the same both times
    And a key a link already has is kept

  Scenario: A missing earlier step warns and the work goes on
    Given the outline step is not done
    When the missing steps are checked for a draft
    Then a warning names the outline step
    And nothing is refused
