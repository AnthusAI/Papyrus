Feature: A rejected name never collects links again, however it is spelled
  An editor, or the AI review, rejects a concept the extractor invented. Rejected stays
  rejected, and a machine never changes an existing concept. The extractor, though, meets
  the same name again every week, and it does not always spell it the same way: "GPT-4"
  in one source is "GPT 4" in another. The knowledge run used to look names up by one
  rule and to key concepts by another, so the second spelling slipped past the rejection
  and links were written to the rejected concept.

  The run now has one identity for a name, the one a concept's key is made of, so every
  spelling of a rejected name is the rejected name. It is dropped before it can make a node
  or a link, the run reports it as dropped because it was rejected earlier, and nothing on
  the map changes. A rejection is also specific to the kind: the same name as a different
  kind of thing is still a fair candidate. This is the first step of learning from what
  people and the review throw away.

  Background:
    Given a site "shipped" with the published items "alpha" and "beta"
    And the extractor proposed the model "GPT-4" in the item "alpha" and the run was imported

  Scenario Outline: A rejected name gets no new link under another spelling
    Given <rejecter> rejected the concept "GPT-4"
    When the extractor proposes the model "GPT 4" in the item "alpha" and the run is imported
    Then the map has no concept "GPT 4"
    And the rejected concept "GPT-4" is exactly as it was and has no new link
    And the import report lists "GPT 4" as dropped because it was rejected earlier

    Examples:
      | rejecter      |
      | the AI review |
      | a person |

  Scenario: The same name as another kind of thing is still a candidate
    Given a person rejected the concept "GPT-4"
    When the extractor proposes the organization "GPT-4" in the item "alpha" and the run is imported
    Then the map has the concept "GPT-4" as a model and as an organization

  Scenario: Another spelling of an accepted name does not make a second concept
    Given a person accepted the concept "GPT-4"
    When the extractor proposes the model "GPT 4" in the item "alpha" and the run is imported
    Then the map has no concept "GPT 4"
    And the accepted concept "GPT-4" is exactly as it was
