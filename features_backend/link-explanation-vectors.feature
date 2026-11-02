@backend @link-explanation-vectors
Feature: The explanation an editor writes on an accepted link is findable in the knowledge base, for the newsroom and never for a public reader
  When an editor accepts a link between two References, or tags a Reference with a concept, they can say why in a note. That explanation is first-class meaning:
  it is the editor's own reading of how two sources relate, and the knowledge query used to be blind to it. Each accepted link with an explanation now has one
  vector in the site's index. Its text names both ends and the explanation, so it can be found on its own. The router's daily pass keeps these vectors current:
  a new or edited explanation is written, an unchanged one costs nothing, and a link later rejected, or whose note is cleared, loses its vector (or, where the
  router's role may not delete, has it marked withdrawn so that no query returns it). The internal knowledge query returns the explanation as an editor's
  explanation and links both References. The explanation was written as an internal note, so the index marks it as an editor's and no public reader query may
  return it: the search filter excludes it for a public request, a second check drops it if the index returns it anyway, and the query engine drops it a third
  time. Suggestions and the context packs ask the index for References and concepts by kind and never meet an explanation. The index, the embeddings and the
  backends are fakes in these scenarios.

  Scenario: An accepted link with an explanation is indexed with both ends and the explanation
    Given the accepted References "alpha" and "beta" linked by an editor who explained why
    When the explanation index is synced
    Then there is one explanation vector that names "alpha", "beta" and the explanation
    And it records both lineage ids, the link's id, its predicate and who decided

  Scenario: A concept tag with an explanation is indexed with the concept's name
    Given the accepted Reference "alpha" tagged with the concept "Evaluation" by an editor who explained why
    When the explanation index is synced
    Then there is one explanation vector that names "alpha", "Evaluation" and the explanation

  Scenario: Links without an accepted explanation are not indexed
    Given links with no note, suggested links, rejected links and a link to a Reference that is still pending
    When the explanation index is synced
    Then there are no explanation vectors

  Scenario: An unchanged explanation costs nothing and an edited one is written again
    Given the accepted References "alpha" and "beta" linked by an editor who explained why
    And the explanation index has been synced
    When the explanation index is synced again
    Then nothing is embedded
    When the editor rewrites the explanation and the explanation index is synced
    Then the explanation vector holds the new text

  Scenario: A link later rejected or with its note cleared loses its vector
    Given the accepted References "alpha" and "beta" linked by an editor who explained why
    And the explanation index has been synced
    When the link is rejected and the explanation index is synced
    Then there are no explanation vectors

  Scenario: Where the router may not delete, the vector is marked withdrawn and no search returns it
    Given the accepted References "alpha" and "beta" linked by an editor who explained why in an index where deleting is not allowed
    And the explanation index has been synced
    When the link is rejected and the explanation index is synced
    Then the explanation vector is marked withdrawn
    And a search that the index answers with it returns nothing

  Scenario: The internal knowledge query returns the explanation as the editor's and links both References
    Given an index that answers a question with an editor's explanation of a link
    When the newsroom asks the internal knowledge query
    Then the result has an explanation attributed to the editor, with the text and a link to each Reference
    And the context text carries the explanation under the editor's attribution

  Scenario: A public reader's question never gets an explanation
    Given an index that answers a question with an editor's explanation of a link
    When a request for a public reader asks the knowledge query
    Then the result holds no explanation and its text does not contain the explanation
    And the search filter excludes explanation vectors for the public request
    And the search drops an explanation vector the index returns for the public request anyway

  Scenario: Suggestions and context packs never pick explanations up
    Given the vector kinds that suggestions and context packs ask the index for
    Then explanation vectors are not among them
