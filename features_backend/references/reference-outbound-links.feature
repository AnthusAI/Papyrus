@backend @reference-outbound-links
Feature: Every Reference records the links on its page at capture, with the content links told apart from navigation, footer and thanks
  When the newsroom captures a Reference's page it keeps every outbound link the page has, and for each one whether it is a content link, a
  navigation link, a footer link, a credit (a thanks or acknowledgements passage) or a link to a person's social profile. Only content links are
  meant to be followed later; this change follows nothing. The rule reads what the page declares about itself (article and main landmarks, nav,
  aside, header and footer, rel tags, theme class names and the words of a thanks passage) and names no publisher, so it can be wrong on a page
  that declares nothing. The links are stored in an attachment beside the captured text, and the curation card keeps only the counts, so the
  Reference row stays small. A capture that failed for lack of text still keeps the links of the page it read. The acceptance page is a saved
  copy of a public blog hub page with a series of articles in an ordered list, one YouTube playlist, one category page, a sidebar, a footer and
  three thanks links. It holds 23 links: 18 series articles (the story counted 17), the category page, the playlist and the three thanks links.

  Scenario: The hub page's series and its playlist are its content links
    Given the saved series hub page
    When the page is captured
    Then its content links are the 18 series articles and the YouTube playlist
    And the category page is not a content link
    And the three thanks links are not content links
    And the sidebar and footer links are not content links

  Scenario: The series is recorded as a list, in page order
    Given the saved series hub page
    When the page is captured
    Then every series article is marked as part of a list
    And the links are in the order the page has them, each address once

  Scenario: The curation run stores the links beside the text and keeps only the counts on the card
    Given the saved series hub page
    When the curation procedure runs for a Reference at that page
    Then the links are stored in an attachment
    And the curation card counts 34 links, 19 of them content links
    And the curation card is small

  Scenario: A page with no links stores no links attachment
    Given an article page with no links
    When the curation procedure runs for a Reference at that page
    Then no links attachment is stored

  Scenario: A page that gave no readable text still keeps the links it had
    Given a page whose only content is a linked image
    When the page is captured
    Then the capture failed with "no_text"
    And its links are recorded

  Scenario: An item enriched by a monitor before it is decided keeps the page's links through delivery
    Given a monitored item whose page had a content link and a navigation link
    When the item is enriched and delivered
    Then the delivered Reference's links attachment holds both links
    And the delivered Reference's curation card counts 2 links, 1 of them a content link
