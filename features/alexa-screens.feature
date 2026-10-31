Feature: An Echo Show shows what the skill is reading
  On a device with a screen the skill shows what it says: the headline feed while it reads the headlines, and the story while it
  reads a story. Touching a card on the feed opens that story exactly as asking for it by voice would. A device without a screen
  gets the same speech and no screen. These scenarios run the real intent handlers against a fake story source; nothing is
  deployed and no Amazon account is used.

  Scenario: The headlines appear as a feed
    Given a listener on an Echo Show
    When they open the skill
    Then the headlines are read aloud
    And the feed of those stories appears under the publication's name, with each story's deck and byline

  Scenario: A story appears while it is read
    Given a listener on an Echo Show has heard the headlines
    When they ask for the second one
    Then that story is read aloud
    And its screen shows the title, byline and the body as plain paragraphs

  Scenario: Touching a card opens that story
    Given a listener on an Echo Show has the feed on screen
    When they touch the third card
    Then the third story is read aloud and its screen appears

  Scenario: A touch that matches no story shows the headlines again
    Given a listener on an Echo Show has the feed on screen
    When a touch names a story past the end of the list
    Then the headlines are read again and the feed appears

  Scenario: A device without a screen only hears the skill
    Given a listener on a speaker without a screen
    When they open the skill and ask for a story
    Then they hear the same speech and no screen is sent
