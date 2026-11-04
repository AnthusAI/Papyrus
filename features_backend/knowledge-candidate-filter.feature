Feature: The knowledge run stops proposing common words as concepts
  The entity extractor reads a site's sources and proposes every span that looks like a
  thing of one of the site's kinds. Left alone it proposed plain words such as
  "attachments", "shows", "material" and "curation", and each became a concept that a
  person or the AI review then had to throw away. Before anything is made, the run now asks
  of each new candidate whether it is a real name.

  Nothing about a subject or a word is written into the engine. The site's own stop-word
  file and entity vocabulary say which words carry no meaning and which kinds exist, and
  the run learns the rest from its own extraction: a one-word name that is nearly always
  written in lower case and that turns up in more documents than names usually do is a
  common word. A name with capitals or digits, such as "GPT-4", and a name of several
  words, such as "dark patterns" or "confinement problem", is kept.

  The run says what it dropped and why, so an editor can see whether the filter was too
  strict. A concept already on the map is never filtered: a machine does not change an
  existing concept.

  Background:
    Given a site "shipped" with the published items "alpha" and "beta"
    And forty documents whose extraction proposes "attachments", "shows", "material", "curation", "GPT-4", "dark patterns" and "confinement problem"
    And the site's entity vocabulary declares the kinds "topic" and "product"

  Scenario: Common words never become concepts and real names do
    When the extraction is imported with the site's vocabulary
    Then the map has the concepts "GPT-4", "dark patterns" and "confinement problem"
    And the map has no concept "attachments", "shows", "material" or "curation"

  Scenario: The import says what it dropped and why
    When the extraction is imported with the site's vocabulary
    Then the import report lists "attachments", "shows", "material" and "curation" as dropped common words
    And the import report counts 4 dropped common words

  Scenario: A concept that was already on the map stays as it is
    Given the extraction was imported before the filter existed
    When the extraction is imported with the site's vocabulary
    Then the concepts on the map are exactly the ones the earlier import made

  Scenario: A site that gives the run no vocabulary and no stop words is not filtered
    When the extraction is imported without the site's files
    Then the map has the concept "attachments"
    And the import report lists no dropped candidate

  Scenario: A kind the vocabulary does not declare is dropped
    Given the site's entity vocabulary declares the kinds "product" only
    When the extraction is imported with the site's vocabulary
    Then the map has no concept "dark patterns"
    And the import report lists "dark patterns" as dropped for a kind that is not in the vocabulary
