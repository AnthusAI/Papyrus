Feature: A site defines its Story types, and the engine knows only which Item types are not Stories
  A Story has a type. Nothing in the engine lists the Story types: wiki pages, doctrine, pages and newsletter issues are the fixed system set, and every other
  Item type is a Story type, so a site's own new type needs no engine change. What a site offers an editor, and which type a new Story gets, is declared in its
  web/projection.json (`storyTypes`), the file the projector already reads; with no declaration the types are the ones the site gives a URL base, and the
  default is an article. Create Story is one action that makes a Story of the default type; the type is a field of the Story, and changing it follows
  versioning: a new version carries the new type and the live page keeps its address until that version is published. A Story whose type the site publishes
  nowhere is recorded as published but gets no page, and the editor is told so.

  Scenario: A site declares its Story types and a default
    Given a site whose projection.json declares the Story types "post" and "guide" with the default "post"
    Then the site offers "post, guide" and its default type is "post"

  Scenario: A site that declares nothing has no default and offers the types it gives a URL base
    Given a site whose type settings are article "articles" and post "posts" and which declares no Story types
    Then the site offers "article, post" and has no default type

  Scenario: A site without a projection.json has no types and no default
    Given a site with no projection.json
    Then the site offers no types and has no default type

  Scenario: A declaration that names a system type is refused
    Given a site whose projection.json declares the default Story type "page"
    Then the declaration is refused because that type is not a Story

  Scenario: The value of a Story with no type is not a type a site can offer
    Given a site whose projection.json declares the default Story type "untyped"
    Then the declaration is refused because that is the value of a Story with no type yet

  Scenario: Only the system set is not a Story
    Then "article", "post", "guide", "case_study", "newsletter_issue" and "untyped" are Story types
    And "wiki_page", "doctrine" and "page" are not

  Scenario: The Stories board and the idea pipeline count a site's own type as a Story
    Given Items of the types "guide", "wiki_page" and "article"
    Then the Stories among them are the guide and the article

  Scenario: With no default, Create Story and the idea pipeline leave the type unset
    Given a site with no projection.json
    When a new Story is made for the site
    Then the Story is stored with no type, as "untyped", and is a draft on the board

  Scenario: A Story with no type cannot be published
    Given a Story with no type
    When an editor publishes it
    Then the publish is refused and says to choose a type first

  Scenario: Choosing a type for a Story with no type makes it publishable
    Given a Story with no type
    When the editor saves it in place as a post
    Then the editor has chosen the post type and publishing now succeeds

  Scenario: A new version changes a Story's type and the live page waits
    Given a published article
    When the editor saves a new version of it as a post
    Then the new version is a post and the published article keeps its type
    And publishing the new version reports that the type changed from "article"

  Scenario: A live Story's type is not changed by saving it in place
    Given a published article
    When the editor saves it in place as a post
    Then the save is refused and says to save a new version

  Scenario: A type with no address is published but builds no page
    Given a site that gives the type "article" the base "articles" and names no other type
    And a published Story of the type "guide"
    When the site pages are built
    Then no page is built for the guide
    And the article has its page under "/articles/"

  Scenario: A type with a URL base builds its page
    Given a site that gives the types "article" and "guide" the bases "articles" and "guides"
    And a published Story of the type "guide"
    When the site pages are built
    Then the guide has its page under "/guides/"

  Scenario: Publishing a version of another type moves the page and leaves a redirect
    Given a site that gives the types "article" and "post" the bases "articles" and "posts"
    And an article that is live under "/articles/moving/"
    When a version of it as a post is published
    Then the page is under "/posts/moving/", the old page is gone and "/articles/moving/" redirects to it

  Scenario: A newsletter issue is an ordinary Story of the type the site configures
    Given a roundup list that names no issue type
    Then the newsletter settings are refused and ask the site for the Story type of its issues
    And a roundup list that names the type "post" is accepted, and its issues are Stories of that type
