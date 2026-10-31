Feature: A listing can show just one Story type
  A site that publishes more than one kind of Story, such as articles and posts, often wants a block that shows only
  one of them: the newest article on a newsroom page, even when a post is newer. Story types are a selection like
  sections and tags, so the same attributes work in an include, in a collection and on any site. A selection that
  names no type behaves exactly as before, and a page depends only on the entries its selection picks.

  Background:
    Given a site that lists the types "article" and "post"
    And a post published after the newest article

  Scenario: A listing with types shows only articles
    When a page includes a listing with types "article" and count 1
    Then the block shows the newest article and no post

  Scenario: A listing with notTypes leaves posts out
    When a page includes a listing with notTypes "post"
    Then the block shows every article and no post

  Scenario: An unknown selection attribute is still refused
    When a page includes a listing with the attribute "type"
    Then the projection fails naming the unknown attribute "type"

  Scenario: A change to an excluded type does not rewrite the page
    Given a page whose listing shows the newest article
    When a post is edited
    Then only the post is rewritten
    When the newest article is edited
    Then the article and the page are rewritten
