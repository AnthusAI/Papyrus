Feature: Editors link, decide on and ask for suggested links through the backend
  An editor links a Reference to another Reference or to a concept, accepts or rejects a link, and asks for suggested links for a
  Reference. The browser does not write the relation itself. Three backend mutations do it as the signed-in person: createReferenceLink
  writes a current link recorded as the person's own doing, decideReferenceLink moves a link to current or rejected and records who decided,
  when and the optional reason and note, and suggestReferenceLinks asks the site's vector index for neighbours and files them as suggestions
  without computing an embedding. Only editors and admins can call them. The rows the backend writes match, field for field, the rows the
  Python command line writes, because both are checked against the same shared examples. These scenarios run the real backend code against an
  in-memory stand-in for the data API.

  Scenario: An editor links two References and the same pair twice leaves one link
    Given the shared link examples
    When an editor links two References as related, in either order
    Then there is one current link recorded as human, and it matches the Python writer

  Scenario: An editor tags a Reference with a concept
    Given the shared link examples
    When an editor tags a Reference with a concept
    Then the link goes from the Reference to the concept and matches the Python writer

  Scenario: An editor rejects a link with a reason and then accepts it
    Given the shared link examples
    When an editor rejects a link with a reason and later accepts it
    Then the link records who decided and when, and matches the Python writer

  Scenario: An editor accepts a machine suggestion
    Given the shared link examples
    When an editor accepts a machine suggestion
    Then the suggestion becomes a current link and matches the Python writer

  Scenario: Only editors can use the three mutations
    Given the shared link examples
    When the backend schema is read
    Then createReferenceLink and decideReferenceLink and suggestReferenceLinks are open to editors and admins only

  Scenario: Bad input is refused in words
    Given the shared link examples
    When a link is asked for with an unknown predicate or a Reference that does not exist
    Then the request is refused in words

  Scenario: Suggesting links needs the knowledge index and no embedding key
    Given the shared link examples
    When links are suggested for a Reference
    Then the suggestion runs against the site's vector index with no embedding key
