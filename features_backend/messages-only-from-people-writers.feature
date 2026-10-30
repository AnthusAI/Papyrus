Feature: Reports, ontology runs, story moves, form triage and email agents write no Messages
  Messages come only from people. A machine process that used to leave a Message behind now
  prints its result, keeps it on the record it is about, or does not record it at all.

  Scenario: A trend report prints its signals and writes nothing
    Given accepted references about a topic in a corpus
    When I build an edition trend report for that topic
    Then the report ranks at least one signal
    And the report carries no records to write

  Scenario: A concept report prints its rankings and writes nothing
    Given accepted references that mention concepts in a corpus
    When I build a concept report of every type
    Then the report has popularity, trending and pagerank sections
    And the report carries no records to write

  Scenario: An ontology run keeps its explanation on the relation, not in a Message
    Given an ontology relation between two concepts
    When the relationship explainer records its explanation
    Then the only record to write is a model attachment owned by the relation
    And no Message and no link relation are written

  Scenario: Marking a form submission handled updates the submission itself
    Given a public form submission that is open
    When an operator marks the submission handled with a note
    Then the submission's own status is handled and its metadata keeps the note
    And no new Message is created
    And the submission no longer lists as open

  Scenario: The agents are not offered a way to write Reference notes
    Given the Tactus tools the newsroom agents can call
    Then the tools include listing Reference notes
    But the tools do not include creating a Reference note
    And the email agent is told that notes come only from people
