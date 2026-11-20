Feature: An X announcement may carry hashtags from the Story's own concepts
  The concepts tagged to a Story are the hashtags worth using when it is announced (PPY-d40025). The Story's hashtags are its accepted concepts, most-used
  first, in CamelCase. The draft may choose at most two of them and puts them after its words; it may use no other hashtag, and it uses none when none fits.
  Nothing here reaches X or a model: the model and the site are stand-ins.

  Scenario: A Story's hashtags are its accepted concepts, most used first
    Given a Story "story-1" tagged with the accepted concepts "voice-cloning" used by 2 Stories and "newsrooms" used by 5 Stories
    When the hashtags of "story-1" are read
    Then the hashtags are "#Newsrooms" then "#VoiceCloning"

  Scenario: A concept nobody accepted is not a hashtag
    Given a Story "story-1" tagged with the accepted concept "newsrooms" used by 1 Stories
    And "story-1" is also tagged with the concept "half-baked" that is only suggested
    When the hashtags of "story-1" are read
    Then the hashtags are "#Newsrooms"

  Scenario: A name that cannot be a hashtag is left out
    Given a Story "story-1" tagged with the accepted concepts "2026" used by 3 Stories and "newsrooms" used by 1 Stories
    When the hashtags of "story-1" are read
    Then the hashtags are "#Newsrooms"

  Scenario: The draft puts the hashtags it chose after its words
    Given the Story offers the hashtags "#Newsrooms" and "#VoiceCloning"
    When the draft chooses the hashtags "#Newsrooms"
    Then the post text ends with "#Newsrooms"
    And every check passes

  Scenario: At most two hashtags are posted
    Given the Story offers the hashtags "#Newsrooms", "#VoiceCloning" and "#Agents"
    When the draft chooses the hashtags "#Newsrooms", "#VoiceCloning" and "#Agents"
    Then the post text ends with "#Newsrooms #VoiceCloning"

  Scenario: A hashtag the Story's concepts do not hold fails the draft
    Given the Story offers the hashtags "#Newsrooms"
    When the draft chooses the hashtags "#Politics"
    Then the check "hashtags" fails saying "#Politics, which is not one of the Story's concepts"

  Scenario: No concept fits, so no hashtag is posted
    Given the Story offers the hashtags "#Newsrooms"
    When the draft chooses no hashtags
    Then the post text has no hashtag
    And every check passes

  Scenario: A Story with no concepts offers none and the draft is told so
    Given the Story offers no hashtags
    When the draft chooses no hashtags
    Then the model was told the Story offers no hashtags
