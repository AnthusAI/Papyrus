Feature: The newsroom home page shows the Cyclotron classifier behind this site's predictions
  At the top right of the newsroom home page (above the list on a phone) a panel says what the classifier is doing: when it last changed or was
  cycled, its latest evaluation number and what that number was measured on, and counts such as the reviewed labels. It shows this site's
  own classifier only. It says only what the Cyclotron's status snapshot says: it never implies learning that did not happen, a missing number
  says "Not measured yet", and a site with no snapshot gets a plain sentence, never a skeleton that waits for ever. Votes made after a snapshot
  are not in it, so the panel shows when the snapshot is from. When the Cyclotron's read-only report is available the panel adds what the classifier
  is learning from, its most recent cycle, how often it agreed with the reviewers (never called accuracy, and "Not compared yet" when nothing was
  compared, never 0%), that agreement day by day and by classifier revision, the held-out evaluation, the counts of labels, and in the expanded details
  the decision elements: the question, the classes, the rubric, and the supporting questions and weights. A site on an older version, or a row before
  the router's first run, has no report and keeps the status-only panel. Everything the report says is shown as text.

  Background:
    Given a newsroom home page with synthetic classifier snapshots at 375 and 1440 pixels

  Scenario: A snapshot is shown in words, top right on a desktop and above the list on a phone
    When the editor opens the home page and the classifier has cycled twice with 41 reviewed labels
    Then the panel says the classifier has cycled twice and when it last changed
    And the panel gives the agreement with reviewers as a percentage and says it was measured on the reviews the Cyclotron selected
    And the panel counts the reviewed labels and the decisions awaiting review
    And the panel says when the snapshot is from and that votes after it are not included yet
    And the panel is in the top right of the header on a desktop and between the title and the list on a phone
    And nothing in the panel has a border, every icon is a Lucide icon, it has no dropdown, and nothing scrolls sideways

  Scenario: A site whose classifier has never cycled is told so plainly
    When the editor opens the home page and the snapshot has no cycle, no last change and no reviewed labels
    Then the panel says it has not cycled yet
    And the agreement says "Not measured yet" and shows no percentage
    And no sentence in the panel implies that the classifier learned anything

  Scenario: A site with no snapshot gets a sentence, not a skeleton
    When the editor opens the home page and the Cyclotron has not reported on this site's classifier yet
    Then the panel says the Cyclotron has not reported on this site's classifier yet, with no skeleton and no empty field
    And when the status cannot be read the panel says so in one sentence and the feed is still shown
    And while the status is being read the panel says it is being read

  Scenario: A page without the status read has no panel
    When the editor opens a home page that has no classifier status source
    Then there is no classifier panel

  Scenario: The report adds learning, agreement with reviewers by day, the held-out evaluation and the counts
    When the editor opens the home page and the Cyclotron's report has seven of nine compared votes over three days
    Then the panel says the classifier is not learning from votes yet, with the report's reason, and when it last cycled
    And the panel says "7 of 9 compared" for agreement with reviewers, never calls it accuracy and shows no percentage for it
    And the panel lists the days newest first with the agreed of compared votes in words and a mark, and the classifier revisions
    And the panel gives the held-out evaluation's reason when there is no number and a percentage when there is one
    And the panel counts the labels, the reviewed decisions and the primed examples and keeps decisions awaiting review out of the top section
    And nothing in the panel has a border, every icon is a Lucide icon, it has no dropdown, and nothing scrolls sideways

  Scenario: The expanded details show the decision elements as text
    When the editor opens the home page and expands the details of a classifier with a report
    Then the details give the question, the classes and the rubric
    And a very long rubric is folded and wraps when opened
    And a classifier with no supporting questions says so in the report's own words and one with weights lists them
    And decisions with no label filed in the engine are explained in words

  Scenario: Before the first decision the report still shows and says nothing is compared
    When the editor opens the home page and the Cyclotron has a report but no status snapshot yet
    Then the panel says "Not compared yet" for agreement with reviewers and never shows 0%
    And the panel says it has not cycled yet and that there are no days with votes
    And the panel says there is no snapshot yet and why, and the details say no decision has completed

  Scenario: An unknown report is dropped, never shown half-read
    When the editor opens the home page and the rows hold reports of several shapes
    Then a report with an unknown schema or a section out of shape is dropped, and the status beside it is kept
    And a row with only a report is kept and a row with only a status is kept
