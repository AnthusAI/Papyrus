Feature: Cited Trends choose how far back to look from the data
  A trend has no natural length. A release can spike for one week; a technique can build for a quarter. Cited Trends therefore does not
  compare a fixed span with the span before it. For each entity it tries the most recent 1, 2, 4, 8, 16, ... weeks, each against all
  the history before it (leaving at least four weeks of baseline), and keeps the window whose count is most surprising once the
  corpus's own growth is allowed for. Trying several windows and keeping the best would find false trends in plain noise, so the best
  p-value is corrected for the number of windows tried (Bonferroni) and an entity counts as trending only when the corrected p-value is
  within 0.01. The chosen window is part of the signal: the model is told "rising over the last N weeks", the draft's cited signals
  describe it, and the draft's evidence records it. The snapshot index publishes each entity's full weekly history (seriesWeekly) for this, so the
  windows grow with the history; a snapshot that only has 26 or eight weeks is scanned over those.

  Scenario: A spike is detected over a short window
    Given a quiet concept that is mentioned 9 times in the latest week
    When the trend windows are scanned
    Then the concept is a trend over a window of 1 week
    And the signal says 9 items in the last week against 0 in the 25 weeks before

  Scenario: A slow build is detected over a long window
    Given a concept that was quiet and then grew a little every week for 16 weeks
    When the trend windows are scanned
    Then the concept is a trend over a window of 16 weeks
    And the model is shown the concept with a window of 16 weeks and its full weekly history

  Scenario: A snapshot with the full weekly history lets a window longer than 26 weeks win
    Given a concept that was quiet for 70 weeks, then grew steadily for 50 weeks
    When the trend windows are scanned
    Then the window is longer than 26 weeks

  Scenario: The same build seen through only the last 26 weeks is limited to those
    Given a concept that was quiet for 70 weeks, then grew steadily for 50 weeks
    When the trend windows are scanned over the last 26 weeks only
    Then the longest window it can try is 16 weeks, and the full history is more surprising

  Scenario: Noise does not make a false trend once the number of windows tried is corrected for
    Given a concept that is mentioned once a week and 5 times in the latest week
    When the trend windows are scanned
    Then that window alone would pass at 0.01 but the corrected p-value does not
    And the concept is not a trend

  Scenario: Steady noise across many entities rarely makes a trend
    Given 500 concepts that are only noise around 2 mentions a week
    When the trend windows are scanned for each
    Then at most 5 of them are trends

  Scenario: A corpus that doubles does not make everything a trend
    Given a concept that keeps its share while the corpus doubles
    When the trend windows are scanned
    Then the concept is not a trend

  Scenario: The draft records the window each cited entity reported
    Given a quiet concept that is mentioned 9 times in the latest week
    When the trend windows are scanned
    And a draft that cites the concept is recorded
    Then the draft's evidence holds a window of 1 week with 9 items against 0 in the 25 weeks before

  Scenario: A snapshot of only eight weeks is still scanned
    Given a quiet concept that is mentioned 9 times in the latest week
    And the snapshot publishes only eight weeks
    When the trend windows are scanned
    Then the concept is a trend over a window of 1 week
    And the baseline is the 7 weeks before the window
