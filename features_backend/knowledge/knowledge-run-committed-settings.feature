Feature: A site's knowledge run settings are committed, reviewed and deployed like everything else
  What a person maintains for a site's knowledge run, the vocabulary of entity kinds and relation types (with the publication's description and
  what each kind is and is not for), the stop words and the guidance for the AI review, used to live only in the job's S3 state, edited by hand
  with no history and no review. They are now files in the repository beside the site's infra/site.json. The job stack ships them with the
  deploy, every stage unpacks them into its work directory, and the task log says where each file came from. The run state is never consulted
  for them, so an old copy there cannot override what was reviewed and deployed; if one is still there the log says it is ignored. A site that
  commits nothing keeps the generic vocabulary and has no stop words or review guidance. The settings are a zip in the deploy's asset bucket,
  so changing them means deploying the job stack, and a run that cannot find them stops instead of quietly using the default. This is synthetic
  content: a harbour logistics publication.

  Background:
    Given a harbour publication "harbour" whose site commits a vocabulary, stop words and review guidance

  Scenario: A stage uses the committed files and says so
    When the stage "corpus-sync" runs and the task log is kept
    Then the work directory's "config/vocabulary.yml" is the committed vocabulary
    And the work directory's "config/stop-words.txt" is the committed stop words
    And the work directory's "config/review-guidance.md" is the committed guidance
    And the task log says "config/vocabulary.yml: committed settings" once, however many times the stage pulled its files

  Scenario: An old copy in the run state does not win, and the log says it was ignored
    Given the run state still holds an old "config/vocabulary.yml" and an old "config/stop-words.txt"
    When the stage "corpus-sync" runs and the task log is kept
    Then the work directory's "config/vocabulary.yml" is the committed vocabulary
    And the work directory's "config/stop-words.txt" is the committed stop words
    And the task log says the run state still holds config files that a run no longer reads, naming both

  Scenario: Only the files the site committed are used and the log says what is missing
    Given the site commits only stop words
    When the stage "corpus-sync" runs and the task log is kept
    Then the task log says "config/vocabulary.yml: generic default"
    And the task log says "config/stop-words.txt: committed settings"
    And the task log says "config/review-guidance.md: none"
    And the work directory has no "config/review-guidance.md"

  Scenario: The committed stop words reach the topic model
    When the stages "corpus-sync", "topic-model" run and the task log is kept
    Then the topic configuration was given the committed stop words file

  Scenario: A run that cannot find its committed settings stops
    Given the deployed settings are missing from the asset bucket
    When the stage "corpus-sync" runs and the task log is kept
    Then the stage failed
    And the failure says the committed settings are not there and the job stack should be deployed again
    And no default vocabulary was used

  Scenario: A settings file the run does not know is refused
    Given the deployed settings hold a file called "notes.txt"
    When the stage "corpus-sync" runs and the task log is kept
    Then the stage failed
    And the failure names "notes.txt" as not a settings file

  Scenario: The settings committed for Machines on Machines and Shipped are valid
    Then the committed vocabularies of "machines-on-machines" and "shipped" name their publication, their kinds and their relation types
    And Machines on Machines' vocabulary has a description and a "what" and "not_for" for every kind
    And Shipped's vocabulary has a description
