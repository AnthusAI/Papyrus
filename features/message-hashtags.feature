Feature: Hashtags typed in a Message link it to the concept
  When a person writes #voice-cloning in a Message and the site has an accepted concept with that name, the Message is linked to the
  concept with a current "related to" edge from the message to the concept, recorded as the person's own doing. The backend does the
  linking from the stored Message, its text and its author, so the browser only says which Message to look at. A hashtag that matches
  no concept, or more than one, creates nothing and is listed on the Message as an unmatched hashtag, a possible new concept for a
  person to decide on. Running it again changes nothing. These scenarios run the real linking code against an in-memory stand-in for the
  data API.

  Scenario: A matching hashtag links the Message to the concept
    Given a person's Message that mentions an accepted concept by hashtag
    When the hashtags in the Message are linked
    Then one current related-to edge goes from the Message to the concept, recorded as human

  Scenario: An unknown hashtag is listed and creates nothing
    Given a person's Message that mentions an unknown hashtag
    When the hashtags in the Message are linked
    Then the hashtag is listed on the Message as unmatched and no edge is written

  Scenario: Linking twice leaves one edge
    Given a person's Message that mentions an accepted concept by hashtag
    When the hashtags in the Message are linked twice
    Then one current related-to edge goes from the Message to the concept, recorded as human

  Scenario: Only the author's own Message is linked
    Given a person's Message that mentions an accepted concept by hashtag
    When someone else asks for its hashtags to be linked
    Then the request is refused in words
