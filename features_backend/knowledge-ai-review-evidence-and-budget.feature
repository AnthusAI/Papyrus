Feature: The AI review accepts a concept only on evidence about it, and spends its calls on every kind of work
  The weekly knowledge run asks a language model to review what the extractor proposed:
  new concepts, new clusters and proposed relations. The model never decides alone. An
  accept counts only when the evidence it quotes is a piece of the source text and names
  the thing.

  That used to be too easy to satisfy. The text shown to the model is the passage around
  each mention, so a sentence that merely names a thing, as a baseline in a comparison or
  one of a list, was accepted as evidence that the thing is a real concept. The gate now
  also needs the quote to be about the thing: the model must say so, and the quote must say
  more than the name. The decision log records which part of the gate decided.

  The review has a ceiling on its calls in one run. Concepts come first and are the most
  numerous, so a long list of them used to use every call and leave the clusters and the
  relations unreviewed. Each kind of work is now owed what it needs, up to a fair share of
  the ceiling: the kinds that need little are served in full, the rest share what is
  left, and a stage may use every call except what the stages after it are owed. A call a
  later stage does not need goes back to the pool.

  Scenario: A concept named only in passing is not accepted
    Given the source says "We compared Tern 3 against Llama-9 on three benchmarks, and Tern 3 won two of them."
    And the extractor proposed the entity "Llama-9"
    And the AI reviewer accepts "Llama-9" quoting "We compared Tern 3 against Llama-9 on three benchmarks" and says it is not about it
    When the entities are reviewed
    Then nothing was accepted
    And the decision for "Llama-9" was refused because the thing is named in passing

  Scenario: A concept the source is about is accepted
    Given the source says "Llama-9 is an open-weight language model that Acme released in June."
    And the extractor proposed the entity "Llama-9"
    And the AI reviewer accepts "Llama-9" quoting "Llama-9 is an open-weight language model that Acme released in June." and says it is about it
    When the entities are reviewed
    Then "Llama-9" was accepted
    And the decision for "Llama-9" records that the quote names the thing and is about it

  Scenario: A bare name is not evidence
    Given the source says "Llama-9 is an open-weight language model that Acme released in June."
    And the extractor proposed the entity "Llama-9"
    And the AI reviewer accepts "Llama-9" quoting "Llama-9" and says it is about it
    When the entities are reviewed
    Then nothing was accepted

  Scenario: The calls are shared fairly between concepts, clusters and relations
    Given the review needs 150 calls for entities, 4 for clusters and 10 for relations
    When the ceiling is 100 calls
    Then entities are owed 86 calls, clusters 4 calls and relations 10 calls

  Scenario: A long list of concepts does not starve the clusters and the relations
    Given the extractor proposed forty-five concepts, one new cluster and one proposed relation are waiting, and the ceiling is 3 calls
    When the review runs over those candidates
    Then the review log says it needed 3 calls for entities, 1 for clusters and 1 for relations
    And the review log says it used 1 call for each of entities, clusters and relations

  Scenario: Only the latest run's clusters are offered for review
    Given the topic model proposed clusters in two runs, an earlier one and the latest
    And the earlier run's clusters are still waiting as proposed
    When the clusters are reviewed
    Then only the latest run's clusters are sent to the reviewer, and the earlier run's are not
    And the call budget for clusters counts only the latest run's clusters
    # The snapshot publishes the latest run's clusters only, so naming an earlier run's cluster would never reach a reader
