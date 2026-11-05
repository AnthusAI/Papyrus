Feature: Concepts have a public page only when the page answer is yes
  The entity step asks Jev three questions about every candidate name, and the third is whether
  the name deserves a wiki page of its own. That answer used to be written into the typed
  output and ignored, so every accepted concept of a public kind got a page, however thin.
  Filing and page are separate: a real name is filed as a concept either way, and only some
  concepts get a page of their own. A concept that has no page stays accepted, filed and
  linkable, and only its page is missing.

  The knowledge run keeps the answer on the concept: the page score (Jev's probability that the
  name deserves a page), the yes or no, and the number of documents the name is in, which is
  shown beside the score and never blended into it. There is no cut-off: concepts are ranked by
  the page score wherever they are listed for review, with the document count beside it. A
  name that is in only one document gets no page until a second document mentions it, however
  much that one document says; the extractor decides that itself and says no.

  A later run updates the machine's answer, and that is the only thing it changes on an
  existing concept. An editor's own decision is kept apart and wins over the machine: an editor
  can give a concept a page when the machine said no, or take the page away when it said yes,
  and a later run never undoes that. Handing the decision back returns the concept to the
  machine's answer.

  A concept that existed before the answer was kept has no answer. It is not treated as a no
  and its page is not taken away, and it is not given a score either: it keeps its page until
  an extraction run answers for it.

  Background:
    Given a site "shipped" with the published items "alpha" and "beta"

  Scenario: The page answer and the document count are kept on the concept
    When the extractor proposes "Tern Migration" with page score 0.83 in 4 documents and the run is imported
    Then the concept "Tern Migration" has page score 0.83, a page answer of yes and 4 documents

  Scenario: A name in one document is kept as a concept with no page
    When the extractor proposes "Kestrel Study" with page score 0.0 in 1 documents and the run is imported
    Then the concept "Kestrel Study" has page score 0.0, a page answer of no and 1 documents

  Scenario: A later run updates the answer and nothing else of the concept
    Given the extractor proposed "Tern Migration" with page score 0.2 in 1 documents and the run was imported
    When the extractor proposes "Tern Migration" with page score 0.9 in 3 documents and the run is imported
    Then the concept "Tern Migration" has page score 0.9, a page answer of yes and 3 documents
    And the concept "Tern Migration" is otherwise exactly as it was

  Scenario: A run that finds the same answer writes nothing
    Given the extractor proposed "Tern Migration" with page score 0.2 in 1 documents and the run was imported
    When the extractor proposes "Tern Migration" with page score 0.2 in 1 documents and the run is imported
    Then the run wrote nothing

  Scenario: Only accepted concepts whose answer is yes get a page, and the others stay filed and linked
    Given the extractor proposed "Tern Migration" with page score 0.9 in 3 documents and the run was imported
    And the extractor proposed "Kestrel Study" with page score 0.1 in 3 documents and the run was imported
    And an editor accepted the concept "Tern Migration"
    And an editor accepted the concept "Kestrel Study"
    Then the wiki gives pages to "Tern Migration" only
    And the concept "Kestrel Study" is accepted and still has its mention link

  Scenario: A concept from before the answer existed keeps its page
    Given the extractor proposed "Old Concept" with no page answer and the run was imported
    And an editor accepted the concept "Old Concept"
    Then the concept "Old Concept" has no page answer
    And the wiki gives pages to "Old Concept" only

  Scenario: The first answer for an older concept decides from then on
    Given the extractor proposed "Old Concept" with no page answer and the run was imported
    And an editor accepted the concept "Old Concept"
    When the extractor proposes "Old Concept" with page score 0.2 in 5 documents and the run is imported
    Then the wiki gives pages to nobody

  Scenario: An editor gives a page against the machine's no, and a later run keeps it
    Given the extractor proposed "Kestrel Study" with page score 0.1 in 3 documents and the run was imported
    And an editor accepted the concept "Kestrel Study"
    When a person gives the concept "Kestrel Study" a page
    And the extractor proposes "Kestrel Study" with page score 0.05 in 3 documents and the run is imported
    Then the wiki gives pages to "Kestrel Study" only
    And the concept "Kestrel Study" has page score 0.05, a page answer of no and 3 documents

  Scenario: An editor takes a page away against the machine's yes, and a later run keeps it away
    Given the extractor proposed "Tern Migration" with page score 0.9 in 3 documents and the run was imported
    And an editor accepted the concept "Tern Migration"
    When a person takes the page of the concept "Tern Migration" away
    And the extractor proposes "Tern Migration" with page score 0.99 in 8 documents and the run is imported
    Then the wiki gives pages to nobody

  Scenario: Handing the decision back returns the concept to the machine's answer
    Given the extractor proposed "Tern Migration" with page score 0.9 in 3 documents and the run was imported
    And an editor accepted the concept "Tern Migration"
    And a person took the page of the concept "Tern Migration" away
    When a person hands the page decision of the concept "Tern Migration" back to the machine
    Then the wiki gives pages to "Tern Migration" only

  Scenario: A rejected concept has no page to give
    Given the extractor proposed "Tern Migration" with page score 0.9 in 3 documents and the run was imported
    And an editor rejected the concept "Tern Migration"
    When a person tries to give the concept "Tern Migration" a page
    Then the command is refused saying the concept is rejected

  Scenario: Concepts are listed for review by page score with the document count beside it
    Given the extractor proposed "Alder Study" with page score 0.4 in 9 documents and the run was imported
    And the extractor proposed "Birch Study" with page score 0.91 in 2 documents and the run was imported
    And the extractor proposed "Cedar Study" with page score 0.91 in 7 documents and the run was imported
    And the extractor proposed "Dune Study" with no page answer and the run was imported
    And the extractor proposed "Elm Study" with page score 0.0 in 1 documents and the run was imported
    When the concepts are listed
    Then the list is "Cedar Study", "Birch Study", "Alder Study", "Elm Study", "Dune Study" in that order
    And "Cedar Study" shows 0.91 and 7 documents, and "Dune Study" shows no answer
