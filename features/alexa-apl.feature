Feature: The Alexa skill shows stories on Echo Show screens
  On a device with a screen the skill answers with APL: a feed of story cards and a story page. A voice-only device gets neither.
  The documents are laid out for every APL viewport profile (round hub, small, medium and large landscape hubs, and the TV),
  use the site's brand colours, and carry meaning in words and shapes rather than colour alone. These scenarios use synthetic
  Alexa requests and the documents themselves; nothing is deployed and no device is needed.

  Scenario: A device with a screen is given a directive and a voice-only device is not
    When a request arrives from a device that supports APL
    Then the skill can show a document
    And a request from a voice-only device gets no directive

  Scenario: The feed directive carries the stories
    When the feed is rendered for a list of stories
    Then each story keeps its position in the feed
    And a story with an image has an image address and a story without one has none
    And the headline and deck are in the datasource with the site theme

  Scenario: The story directive carries the whole story
    When a story is rendered for the screen
    Then the datasource has the title, the byline with the date and the body paragraphs
    And the hero image is left out when the story has none

  Scenario: Touching a card opens that story
    When a person touches the third card of the feed
    Then the touch handler opens the story at index two
    And a touch it cannot read opens nothing

  Scenario: Each document is valid APL for every viewport profile
    When the feed and story documents are inspected
    Then each is an APL document of version 2023.3 or newer
    And each has sizes for the round hub, the three landscape hubs and the TV
    And neither uses borders or dividers
    And the text sizes are readable

  Scenario: The screen colours come from the site
    When a site sets no theme
    Then the documents use the Pilobolus dark brand colours
    And a site theme is validated for colour format and text contrast

  Scenario: Every document can be previewed for every profile
    When the preview fixtures are rendered
    Then there is one fixture per document and viewport profile for the APL authoring tool
