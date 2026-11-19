@backend @quality-ranking
Feature: The time-bucketed quality ranking is one specified module
  Every list of Stories and References that ranks by quality does it with one module, src/papyrus_content/quality_ranking.py, written down in
  docs/quality-ranking.md. The newest window comes first, and inside a window the human rating comes before the Cyclotron's guess. Windows are rolling and
  counted back from a UTC day, so a rating never moves an item to another window and only time does. Nothing is ever dropped: an older window follows the
  newer ones, each ranked inside itself. The Stories listings, the References includes, the Worth Watching row and the home page all call it.

  Inside a window the order is three, four and five stars (the most stars first), then items nobody rated by Cyclotron confidence with the unscored last,
  then one and two stars. Equal items go to the newest arrival and then the key. A missing confidence is not a number: it ranks below every scored item.

  With the site's quality floor on (three-star-floor.feature) the unrated and one-to-two-star tiers cannot reach a public page, so the public order is the
  rating and then the confidence among items at the floor. The newsroom keeps every tier, and a site with no floor keeps every tier everywhere.

  Scenario: The newest window comes first
    Given Stories published in three different weeks
    When they are ranked with week windows
    Then every Story of the newest week precedes every Story of the next

  Scenario: A human rating beats a prediction
    Given a four-star Reference with low Cyclotron confidence and an unrated one with high confidence in the same window
    When they are ranked
    Then the four-star Reference comes first

  Scenario: Unscored is not fifty percent
    Given an accepted Reference the Cyclotron never scored, and scored unrated ones with confidence 0.5 and 0.0
    When they are ranked
    Then the unscored Reference comes after both scored ones

  Scenario: Low ratings sink
    Given a one-star Reference the Cyclotron likes and an unrated one it does not
    When they are ranked
    Then the unrated Reference comes first

  Scenario: A rating does not move windows
    Given References dated across three weeks
    When every Reference is rated and ranked
    Then each Reference is in the window its date gives and the windows come newest first

  Scenario: Time moves windows
    Given a Reference that turns seven days old today
    When the ranking is made today and the day before
    Then it follows every newer Reference today and precedes the older window the day before

  Scenario: A subset keeps the order
    Given a ranked list of Stories
    When a section filter is applied to it
    Then the filtered list is in the same relative order as the whole list ranked

  Scenario: Nothing is dropped
    Given a ranked list of Stories and References, rated and unrated and some with no date
    Then every item is still in the ranked list

  Scenario: One implementation
    Then the Stories, the References, the Worth Watching row and the home page order with the functions of quality_ranking and define no ranking of their own
