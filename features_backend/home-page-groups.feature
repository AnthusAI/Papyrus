Feature: A home page is built from small groups that are best first, full, and never repeat
  A site's home page is a rhythm of small groups: the best recent Stories, then a few from each of several sections,
  then videos, then References that link off the site. Each group shows its best items first and largest, a group that
  has nothing is skipped, and nothing appears twice on a page. The page's author says all of this in include lines; the
  site only draws the cards. Stars decide the order and are never printed. A site that does not use these options
  renders exactly as before.

  Background:
    Given a site with the sections "privacy", "law" and "science"
    And articles and posts in those sections, where "law" has no article

  Scenario: One group per section, the best section first
    When a page includes a listing of articles with posts as the fallback, three sections, two then one Story each
    Then the groups are law, privacy and science
    And law shows its two posts because it has no article
    And every group says how many cards it holds and that its first card is the largest

  Scenario: A section with no article shows its posts, and only then
    When a page includes an article listing for "law" with posts as the fallback
    Then the block shows the posts of law, best first
    When a page includes an article listing for "privacy" with posts as the fallback
    Then the block shows the article of privacy and no post

  Scenario: A Story is not shown twice on one page
    When a page includes the groups and then a unique listing of every post
    Then the later listing leaves out every Story the groups showed

  Scenario: Without the unique option listings repeat as they always did
    When a page includes the groups and then a plain listing of every post
    Then the later listing repeats the posts the groups showed

  Scenario: A wrapper can say how many cards it holds
    When a page includes a counted listing of three posts
    Then the wrapper carries the count 3 and the lead class

  Scenario: A group option on its own is refused
    When a page includes a listing with sections 2 and a count
    Then the projection fails saying a group takes per

  Scenario: References can be asked for with or without a picture
    Given References, some with a picture and some without
    When a page asks for confident References with no picture
    Then only the References without a picture are drawn

  Scenario: Videos and Just Found come in quality order
    Given videos with stars and with predictions
    When a page asks for confident videos
    Then the starred video is first, then the others by prediction

  Scenario: An explainer card sits first in a References grid
    Given accepted References
    When a page asks for References with an explainer and counts
    Then the explainer card is the first item of the grid and is not counted
