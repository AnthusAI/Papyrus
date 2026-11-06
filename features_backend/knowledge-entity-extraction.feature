Feature: Jev decides which names in the texts are real, what kind they are and whether they deserve a page
  The weekly knowledge run has to find the entities in a publication's texts. It used to
  hand the texts to a local model that tagged spans, ran for minutes on the CPU and needed
  gigabytes of weights in the image. The run now reads the texts itself, with no model, to
  find the names that could be concepts, and asks Jev one request per distinct name with three
  questions about the name as it is used in a few passages from different documents: is it a
  real, specific thing, which of the publication's kinds is it, and would a reader look it up,
  so that it deserves a wiki page of its own? Asking once per name, not once per mention, keeps
  the bill small, and the answers are remembered, so a second run over the same texts asks
  nothing. The answers are remembered against the exact wording of the questions and the
  description of the publication, so rewording either makes the run ask again.

  Filing and page are two separate answers. The first decides whether the name is an entity at
  all: a name Jev does not call real is left out. The entity's score is Jev's confidence that
  the name is real, and nothing is cut off by that confidence, because the import's candidate
  filter and the AI review decide what stays. The page answer travels beside it on every
  proposed entity, as a score and a yes or no, so that later steps can rank names by it. A name
  that appears in only one document outside the reference lists never gets a page, whatever Jev said: that
  is decided by the extractor, not left to the wording of the prompt.

  The publication is described to Jev by the "description" in the site's vocabulary, so every
  site says what its own publication is about. A name the wiki already holds is not asked about:
  its mentions point at the accepted entity. Jev does not propose relations, so the file has none.

  Background:
    Given a corpus of two documents that both read "Tern3 beat GPT-4 today. Maple Lab built Tern3."
    And the publication's vocabulary has the kinds "model" and "organization"
    And the wiki already holds the model "GPT-4" as "model--gpt-4"
    And Jev answers "Tern3" is a real model with confidence 0.7 and page 0.8, and "Maple Lab" is a real organization with confidence 0.9 and page 0.3

  Scenario: Every mention of a real name is an entity of the kind Jev chose
    When the entities are extracted
    Then the item "doc-1" has the proposed model "Tern3" twice, with confidence 0.7
    And the item "doc-1" has the proposed organization "Maple Lab" once, with confidence 0.9
    And the file has no relations

  Scenario: The page answer is kept beside the score for every proposed name
    When the entities are extracted
    Then the item "doc-1" has "Tern3" with page score 0.8 and a page
    And the item "doc-1" has "Maple Lab" with page score 0.3 and no page

  Scenario: A name the wiki holds resolves to its entity without asking Jev
    When the entities are extracted
    Then the item "doc-1" has the resolved model "GPT-4" with the entity key "model--gpt-4"
    And Jev was not asked about "GPT-4"

  Scenario: A modest confidence that a name is real is kept, not cut off
    Given Jev answers "Tern3" is a real model with confidence 0.51 and page 0.8
    When the entities are extracted
    Then the item "doc-1" has the proposed model "Tern3" twice, with confidence 0.51

  Scenario: A name Jev does not call real is left out
    Given Jev answers "Tern3" is a real model with confidence 0.2 and page 0.8
    When the entities are extracted
    Then the item "doc-1" has no entity "Tern3"
    And the item "doc-1" has the proposed organization "Maple Lab" once, with confidence 0.9

  Scenario: A name in only one document never gets a page, however often that document mentions it
    Given a corpus of two documents that read "Tern3 beat Maple Lab. Tern3 won again." and "Maple Lab won."
    And Jev answers "Tern3" is a real model with confidence 0.9 and page 0.95, and "Maple Lab" is a real organization with confidence 0.9 and page 0.95
    When the entities are extracted
    Then the item "doc-1" has "Tern3" with page score 0.0 and no page
    And the item "doc-2" has "Maple Lab" with page score 0.95 and a page

  Scenario: One request carries the three questions and the publication's own description
    Given the publication's vocabulary describes it as "a publication about garden robots"
    When the entities are extracted
    Then every request to Jev asks, in this order, whether the name is real, which kind it is and whether it deserves a page
    And every request describes the publication as "a publication about garden robots, building a wiki of concepts"
    And the kinds offered to Jev are "model" and "organization" and no answer for something that is not a concept

  Scenario: A name is asked about once, however often it appears
    When the entities are extracted
    Then Jev was asked about "Tern3" once and about "Maple Lab" once

  Scenario: A second run over the same texts asks nothing and costs nothing
    Given the entities were extracted
    When the entities are extracted again
    Then Jev was not asked anything
    And the run reports no paid calls
    And the file is the same as the first time

  Scenario: Describing the publication differently makes the run ask again
    Given the entities were extracted
    And the publication's vocabulary describes it as "a publication about garden robots"
    When the entities are extracted again
    Then Jev was asked about "Tern3" once and about "Maple Lab" once

  Scenario: A word is never found inside a longer word
    Given a corpus of two documents that both read "The Organization of Experts met. Organization of Experts spoke."
    When the entities are extracted
    Then no entity of the file starts or ends in the middle of a word

  Scenario: A name never runs across a line break
    Given a corpus of two documents that both read "ChatGPT" and "Medical" in separate paragraphs
    When the entities are extracted
    Then no entity of the file spans a line break

  Scenario: A name in a reference list is not a mention
    Given a corpus of two documents that both read "Tern3 won.\n\n## References\n\nSmith J. Heron Labs. 2024.\n\n## Appendix\n\nTern3 lost."
    When the entities are extracted
    Then Jev was not asked about "Heron Labs"
    And Jev was asked only once about "Tern3"

  Scenario: A citation number stuck to a name is not part of the name
    Given a corpus of two documents that both read "Maple Labs34 agreed." followed by a reference list of 40 entries
    When the entities are extracted
    Then Jev was asked only once about "Maple Labs"
    And Jev was not asked about "Maple Labs34"

  Scenario: A name with an apostrophe inside it stays whole
    Given a corpus of two documents that both read "we heard O'Connell speak."
    When the entities are extracted
    Then Jev was asked only once about "O'Connell"

  Scenario: A document's title is not a name to file
    Given a corpus of two documents that both read "# Heron Networks Report\n\nTern3 won."
    When the entities are extracted
    Then Jev was not asked about "Heron Networks Report"
    And Jev was asked only once about "Tern3"

  Scenario: The number of documents a name is in is kept beside its page score
    When the entities are extracted
    Then the item "doc-1" has "Tern3" with page score 0.8 and 2 documents
    And the item "doc-1" has "Maple Lab" with page score 0.3 and 2 documents

  Scenario: A heading at any level is not a name to file
    Given a corpus of two documents that both read "## Experimental Design\n\nTern3 won.\n\n### Tern Migration\n\nMore."
    When the entities are extracted
    Then Jev was not asked about "Experimental Design"
    And Jev was not asked about "Tern Migration"
    And Jev was asked only once about "Tern3"

  Scenario: A heading that lists section names gives none of them
    Given a corpus of two documents that both read "## Materials and Methods\n\nTern3 won.\n\n### Authors and Affiliations\n\nMore."
    When the entities are extracted
    Then Jev was not asked about "Materials"
    And Jev was not asked about "Methods"
    And Jev was not asked about "Authors"
    And Jev was not asked about "Affiliations"
    And Jev was asked only once about "Tern3"

  Scenario: A section name that the text also uses stays a candidate
    Given a corpus of two documents that both read "## Tern Migration\n\nWe saw Tern Migration begin."
    When the entities are extracted
    Then Jev was asked only once about "Tern Migration"

  Scenario: A date, a bare number or a quantity is not a name
    Given a corpus of two documents that both read "Tern3 ran on October 22 and 23 at Hz and 10 for 3.5 weeks, 5 March 2024 and 10 Hz."
    When the entities are extracted
    Then Jev was not asked about "October 22"
    And Jev was not asked about "Hz"
    And Jev was not asked about "10"
    And Jev was not asked about "March 2024"
    And Jev was asked only once about "Tern3"

  Scenario: Two names joined by "and" are two names
    Given a corpus of two documents that both read "Cedar Lab and Maple Lab agreed."
    When the entities are extracted
    Then Jev was asked about "Cedar Lab" once and about "Maple Lab" once
    And Jev was not asked about "Cedar Lab and Maple Lab"

  Scenario: One proper name that contains "and" stays one name
    Given a corpus of two documents that both read "It was the Center for Democracy and Technology that spoke."
    When the entities are extracted
    Then Jev was asked only once about "Center for Democracy and Technology"
    And Jev was not asked about "Technology"

  Scenario: A name Jev does not answer fails the run without losing what was paid for
    Given Jev does not answer for "Maple Lab"
    When the entities are extracted
    Then the command fails saying Jev gave no answer for 1 name
    And no entities file is written
    And Jev's answer for "Tern3" is kept, so running again asks only about "Maple Lab"
