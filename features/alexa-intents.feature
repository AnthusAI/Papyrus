Feature: A listener hears a site's published stories through Alexa
  The `alexa` skill answers every request the Alexa service sends: it reads the latest headlines, reads a story the listener picks,
  moves between stories and helps or leaves when asked. The words come from the site's own content and settings, never from the
  skill's code. These scenarios run the real intent handlers against a fake story source and a faked public projection; nothing
  is deployed and no Amazon account is used.

  Scenario: Opening the skill reads the latest five headlines
    Given a site with six published stories
    When a listener opens the skill
    Then the five newest headlines are read in order under the site's publication name
    And the listener is asked which story they want and the session stays open

  Scenario: Opening the skill on a site with no stories says so
    Given a site with no published stories
    When a listener opens the skill
    Then the skill says there are no published stories and ends

  Scenario: A story is read by ordinal or by number
    Given the listener has heard the headlines
    When they ask for the second one, or for story number four
    Then the skill reads that story's byline, deck and the first part of its body
    And it offers to say next for the next story

  Scenario: A story number that does not exist is explained
    Given the listener has heard the headlines
    When they ask for a story that is not in the list, or give no number
    Then the skill says how many stories there are and keeps the session open

  Scenario: Next, previous and repeat move through the stories
    Given the listener has heard the headlines
    When they say next, previous and repeat
    Then the skill moves one story at a time and re-reads the current one
    And it says so at the first and the last story instead of going past them

  Scenario: Repeat at the headlines reads the headlines again
    Given the listener has heard the headlines
    When they say repeat before choosing a story
    Then the headlines are read again

  Scenario: A story that has gone away sends the listener back to the headlines
    Given the listener has heard the headlines
    When they ask for a story that was unpublished in the meantime
    Then the skill apologises and reads fresh headlines

  Scenario: Help explains what can be said
    When a listener asks for help
    Then the skill explains numbers, next, previous, repeat, headlines and stop and keeps listening

  Scenario: Stop and cancel say goodbye
    When a listener says stop or cancel
    Then the skill says goodbye and ends the session

  Scenario: Something the skill does not understand reads the headlines
    When a listener says something the skill cannot match
    Then the skill says it did not catch that and reads the headlines, so there is always something to choose
    And the session stays open

  Scenario: Asking for the list in everyday words reads the headlines
    Given a listener who reaches the skill with "ask pilobolus newsroom for the headlines"
    When they ask for the headlines, the stories, the articles or the posts, or say they do not know what the stories are
    Then the latest headlines are read, with a welcome when the session is new
    And asking for a story without a number reads the list instead of asking for a number

  Scenario: Going home returns to fresh headlines
    Given the listener is reading a story
    When they ask to go home
    Then the headlines are fetched and read again
    And the next story is the first one

  Scenario: Ending the session needs no speech
    When Alexa reports that the session ended
    Then the skill answers without speaking

  Scenario: Everything spoken is escaped
    Given stories whose titles, bylines and text contain ampersands, angle brackets and quotes
    When they are read aloud
    Then the speech is well formed and never carries a raw markup character

  Scenario: A long story is read in short parts
    Given a story far longer than a minute of speech
    When it is read aloud
    Then the first part starts with the title, byline and deck and stops at a whole sentence after about a minute
    And the listener can say continue for the next part, repeat for the same part, and hears when the story ends
    And a byline that already starts with "by" is not read as "by by"

  Scenario: A single endless sentence is shortened at a word
    Given a sentence longer than the room there is
    When it is fitted into the speech
    Then it is cut at a word boundary

  Scenario: Speech follows the structure of the Markus document
    Given a Markus story with headings, lists, directives, code, an image and a table
    When it is turned into speech
    Then the document's nodes are read in order and the parts that cannot be heard are described or skipped
    And a stored body IR is used instead of the source when there is one

  Scenario: The interaction model carries every intent
    When the skill package is generated
    Then it holds the required built-in intents and a story intent with natural samples for ordinals and numbers

  Scenario: Stories come from the site's public projection
    Given a site whose public listing and Markdown twins are served
    When the skill lists and reads stories
    Then the newest entries come from the listing, the body from the story's Markdown twin and older stories from the search index
    And a missing twin or an unlisted story is no story and a listing entry never leads to another host
    And a site without a public origin fails loudly instead of answering with nothing

  Scenario: The Markdown twin's header is separated from the story
    When a Markdown twin is read
    Then its title, summary, byline and canonical link are split from the Markus body
