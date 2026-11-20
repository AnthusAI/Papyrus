Feature: Cited Trends picks news, not volume
  Every week the trend-story path reads the knowledge snapshot and picks the entities a story can be about. Counts alone mislead: a
  licence, a task or a platform that nearly every model mentions has the biggest counts every week and rises with the whole corpus, so it
  carries no news. The path therefore scores each entity by how far its mentions in the last four weeks rose above what its own
  earlier four weeks, scaled by the growth of the whole corpus, would lead us to expect. The score is a plain Poisson surprise; there is
  no model in it, and the same snapshot always gives the same entities. Entities of the broad kinds (licence, task, platform) are
  demoted and never anchor a story. They may still appear beside the anchors as context, and the model is told that a context signal is
  never the subject of a headline. Only makers, model families, models, concepts and techniques can anchor a draft.

  A maker also has to be notable before a story can rest on it. A maker is notable when it is on the watchlist, or the site has written
  about it in the window, or at least two of its models were recorded in the window and their likes add up to 100 or their downloads to
  10,000, with at least 10 likes either way because downloads alone are not notability (the thresholds are configuration with those defaults). One individual who uploaded a handful of small fine-tunes cannot anchor
  a draft, however sharp the jump looks. The run record lists who was chosen and who was passed over, with the reason.

  The published trending list in the weekly snapshot uses the same score, so the site's own trending list is meaningful as well.

  Background:
    Given the knowledge snapshot of a week in which a licence, a task and a platform carry the biggest counts
    And NVIDIA released four models with 640 likes between them
    And an individual account released five small models with 30 likes between them

  Scenario: Broad kinds with the biggest counts are not anchors
    When the operator reads which entities become signals
    Then the licence "MIT", the task "text-generation" and the platform "Hugging Face" are not anchors

  Scenario: An organisation with several liked models can anchor a draft
    When the operator reads which entities become signals
    Then "NVIDIA" is an anchor, notable for 4 models and 640 likes

  Scenario: One individual with few likes cannot anchor a draft, and the run says why
    When the operator reads which entities become signals
    Then "emonHasan01" is not an anchor
    And the run record lists "emonHasan01" as passed over because the maker is below the notability bar, with 5 models and 30 likes

  Scenario: Downloads alone are not notability
    Given the individual's three models have 90000 downloads each and 3 likes between them
    When the operator reads which entities become signals
    Then "emonHasan01" is not an anchor

  Scenario: A watchlisted maker can anchor a draft whatever its numbers
    Given the maker "emonHasan01" is on the watchlist
    When the operator reads which entities become signals
    Then "emonHasan01" is an anchor, notable because it is watchlisted

  Scenario: A broad kind beside the anchors is offered as context and the model is told so
    When the operator reads the signals of the snapshot
    Then the task "text-generation" and the licence "MIT" are signals with the role context
    And the model sees them marked as context
    And the prompt forbids a headline about a context signal

  Scenario: The thresholds are configuration
    Given the operator lowers the likes threshold to 10
    When the operator reads which entities become signals
    Then "emonHasan01" is an anchor

  Scenario: The published trending list demotes the broad kinds
    Given a snapshot build in which a licence and a task rose with the corpus while a maker gained share
    When the snapshot is built
    Then the trending list holds the maker and neither the licence nor the task
