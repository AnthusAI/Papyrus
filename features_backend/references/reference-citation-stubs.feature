@backend @reference-citation-stubs
Feature: References the citation graph made on its own are archived, and a monitor brings one back when it finds the paper
  Reading a paper's bibliography creates a pending Reference for every work it cites. Nobody chose those References: they carry the
  citation graph's own markers (the change reason "grobid-citation-graph", the status reason "auto-created from GROBID citation graph" and the
  system actor "papyrus-reference-url-text"), and on a research publication thousands of them bury the pending feed. The command
  "papyrus references retire-citation-stubs" archives the ones that are still exactly what the citation graph made: current, pending, those
  markers, that actor, no star rating and no recorded vote. A prediction does not protect one, because a prediction is a machine's guess.
  Everything else is counted as skipped and left alone. The command archives and never deletes: the record, its prediction and its citation
  relations stay, only the status and the feed keys change, and it records no vote, so nothing trains the Cyclotron. The archive is signed by
  its own machine actor. When a monitor later finds a paper whose stub the machine archived, intake returns that one Reference to pending, so
  it enters the feeds and the Cyclotron predicts it. Intake touches no other archived Reference: a rejected one, or one a person archived,
  stays exactly as it is. Nothing here touches production: the backend is in memory.

  Scenario: Only the stubs nobody touched are archived
    Given a corpus with 3 untouched citation stubs, 1 starred citation stub, 1 citation stub a person reopened and 1 paper a monitor found
    When the citation stubs are retired
    Then 3 References are archived
    And the retirement counts say 6 scanned, 3 eligible and 3 skipped
    And the starred stub, the reopened stub and the monitor's paper are still pending

  Scenario: A stub that has a prediction is still archived
    Given a corpus with 1 untouched citation stub that has a prediction
    When the citation stubs are retired
    Then 1 Reference is archived
    And the archived stub still records its prediction

  Scenario: A dry run writes nothing
    Given a corpus with 3 untouched citation stubs, 1 starred citation stub, 1 citation stub a person reopened and 1 paper a monitor found
    When the citation stubs are retired as a dry run
    Then no stub was written or changed
    And the retirement counts say 6 scanned, 3 eligible and 0 written

  Scenario: The counts say which stubs have a link and which have been cited
    Given a corpus with citation stubs: 2 with a link and no citations, 1 with a link and 4 citations, 2 without a link
    When the citation stubs are retired as a dry run
    Then the retirement counts say 3 with a link, 2 without a link and 1 cited

  Scenario: An archived stub is in neither References feed and nothing is deleted
    Given a corpus with 1 untouched citation stub that has a prediction
    When the citation stubs are retired
    Then the archived stub is in no feed
    And the archived stub is still in the corpus with its link
    And the archived stub is signed by the machine and records no vote

  Scenario: A starred stub is skipped
    Given a corpus with 1 starred citation stub
    When the citation stubs are retired
    Then no stub was written or changed
    And the retirement counts say 1 skipped because it is starred

  Scenario: A stub a person touched is skipped
    Given a corpus with 1 citation stub a person reopened
    When the citation stubs are retired
    Then no stub was written or changed
    And the retirement counts say 1 skipped because its actor is not the system actor

  Scenario: Running it again is a no-op
    Given a corpus with 3 untouched citation stubs, 1 starred citation stub, 1 citation stub a person reopened and 1 paper a monitor found
    When the citation stubs are retired
    And the citation stubs are retired again
    Then the second run scanned 3 and wrote nothing

  Scenario: A monitor that finds the paper restores a stub the machine archived
    Given a citation stub the machine archived
    When a monitor finds that paper and the Cyclotron predicts it
    Then the stub is pending again and in the unrated feed
    And the stub has the prediction of the Cyclotron
    And no second Reference was created

  Scenario: A monitor does not restore a rejected match
    Given a citation stub an editor rejected
    When a monitor finds that paper
    Then the Reference is exactly as the editor left it

  Scenario: A monitor does not restore a match a person archived
    Given a citation stub a person archived
    When a monitor finds that paper
    Then the Reference is exactly as the person left it
