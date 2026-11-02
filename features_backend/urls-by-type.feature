Feature: A Story's type decides where it is published; its section is its topic
  A Story has a type (an article, a post) and a section (the topic it is about, such as Agent Security). They are two
  attributes. A site chooses where its pages live by keying a URL base on the Item type (`urls.types`), on the section
  (`urls.sections`), or on both, and a Story's topic stops having to match the folder it is published in. A site that
  names only sections behaves exactly as before, so the seven sites move one at a time and every address that has been
  published stays where it is. The stored section is a real section id or nothing, never the name of the type.

  Scenario: An article about a topic is published at the base of its type
    Given a site whose articles have the base "articles" in the type settings
    And an article about "agent-security", an article with no section and an article whose section is the old placeholder
    When the URL layout is projected
    Then the three articles have pages under "/articles/"
    And no page is published under "/agent-security/"
    And the articles listing, the sitemap and the feed name the three addresses

  Scenario: A topic section is still a listing of its own through a collection
    Given a site whose articles have the base "articles" in the type settings
    And a collection that selects the section "agent-security"
    And an article about "agent-security" and an article about "agent-engineering"
    When the URL layout is projected
    Then the collection lists only the article about "agent-security"
    And the articles listing has both articles

  Scenario: A post has a base of its own
    Given a site with the type settings article "articles" and post "posts"
    And an article and a post about "agent-security"
    When the URL layout is projected
    Then the article is published under "/articles/" and the post under "/posts/"

  Scenario: A site that names only sections is unchanged
    Given a site that keys its articles on the section "articles"
    And two articles stored with the section "articles"
    When the URL layout is projected
    Then the same files are written as for a site that keys them on the type with no stored section

  Scenario: A section the site declares wins over the type
    Given a site whose articles have the base "articles" and which declares the section "rulings" with the base "rulings"
    And an article about "rulings" and an article about "agent-security"
    When the URL layout is projected
    Then the article about "rulings" is published under "/rulings/" and the other under "/articles/"

  Scenario: A section title kept from before the ids is read as the section
    Given a site whose section "aws" has the base "aws" and answers to the stored value "AWS"
    And one article stored with the section "AWS" and one with the section "aws"
    When the URL layout is projected
    Then both articles are published under "/aws/" and listed together

  Scenario: Only types in the tag selection narrow the tag pages
    Given a site whose tag pages cover only the type "article"
    And an article tagged "alpha" and a page tagged "beta"
    When the URL layout is projected
    Then there is a tag page for "alpha" and none for "beta"

  Scenario: A configuration that makes two groups share a base is refused
    When a site's type settings give "article" the base "essays" while a section already has the base "essays"
    Then the settings are refused naming the type

  Scenario: A new Story with no section stores none
    When a Story is created from an Assignment that names no section
    Then the Story's section is empty and its draft slug keeps its usual shape

  Scenario: An idea is filed under the id of the section it names
    Given a site with the section "guides" titled "Before You File"
    When an idea names the section "Before You File"
    Then the Story is filed under the section "guides"

  Scenario: The plan names what would change and writes nothing
    Given the stored sections of a site: "articles", "unsectioned", "AWS", "aws", "Papyrus" and a page folder "platform"
    When the section migration is planned against a configuration that keys articles on their type
    Then "articles" and "unsectioned" would be cleared and "AWS" would become "aws"
    And "aws" and the page folder "platform" are left alone
    And "Papyrus" is listed as needing a decision and nothing about it changes
    And nothing has been written

  Scenario: The plan is blocked while the configuration still needs the old value
    Given the stored sections of a site: "articles"
    When the section migration is planned against a configuration that keys articles on the section "articles"
    Then the plan is blocked and applying it is refused

  Scenario: The comparison finds no moved address when only the key changes
    Given a snapshot of published articles stored with the section "articles"
    When the snapshot is projected with the section key and again with the type key and the cleared sections
    Then the two projections have the same paths, sitemap, feeds and redirects

  Scenario: The comparison finds a base that moved
    Given a snapshot of published articles stored with the section "articles"
    When the snapshot is projected with the section key and again with a type base of "stories"
    Then the comparison reports the removed and the added addresses and fails
