Feature: An editor creates a Story from any Reference in one tap
  The Reference card and detail have a Create Story action. One tap makes a draft Story at the copywriting stage, linked to the Reference, and opens it in the
  article editor ready to write. The Story is of the site's default type, when its projection.json names one, and has no type yet when it does not; the editor sets or
  changes the type in the Story, and a Story with no type cannot be published. Its title is the Reference's title. Its text starts from the summary the
  newsroom already generated for the Reference, followed by the source link and who it came from; a Reference with no summary starts with the source link alone,
  and no text is ever invented. The one thing taken from the Reference besides that is the picture the newsroom already found for it, which stays a remote address
  credited to its site and recorded with the page it came from. It is another site's picture, so the editor sees a plain note to check the rights before
  publishing. The Story has a section only when the site has exactly one. Creating a Story never changes the Reference's accepted, rejected or pending status
  by itself: the editor's own Accept, when the Reference is pending, is a vote recorded through the existing review path. A Reference that already has a Story is
  not given a second one silently: the action returns the existing Story, and a second Story is made only on a deliberate second request. A summary that repeats
  the source's own words is left out, as the copy guard of every other path requires. Once a Story is based on a Reference, the idea pipeline no longer offers that
  Reference as a single-item idea.

  Background:
    Given a pending Reference "Clef decision models" from "blog.example.com" with a preview image, captured text and a generated summary

  Scenario: One tap makes a linked article at copywriting started from the summary
    When an editor creates a Story from the Reference
    Then a draft Story exists at the copywriting stage titled "Clef decision models"
    And its body starts with the preview image credited to "Example Blog"
    And its body then has the Reference's generated summary and a source line linking the Reference
    And the Story is linked to the Reference as "based_on"
    And the Reference lists the Story among the stories based on it

  Scenario: The front matter records where the draft and the image came from
    When an editor creates a Story from the Reference
    Then the Story's front matter says it was started from the Reference with its summary included
    And the Story's front matter records the image address, its credit and the page it came from

  Scenario: A Reference with no summary starts with the source link alone
    Given the Reference has no generated summary
    When an editor creates a Story from the Reference
    Then the Story's body has the source line and no other text beyond the image

  Scenario: A Reference with no preview image gives a Story with no image
    Given the Reference has no preview image
    When an editor creates a Story from the Reference
    Then the Story's body has no image

  Scenario: The Story is of the site's default type
    Given the site's default Story type is "guide"
    When an editor creates a Story from the Reference
    Then the Story is a guide

  Scenario: A Story has no type when the site names no default
    When an editor creates a Story from the Reference
    Then the Story is untyped

  Scenario: A type that is not a Story is refused
    When an editor asks for a Story of the type "wiki_page"
    Then no Story is made and the editor is told that type is not a Story

  Scenario: Creating a Story never changes the Reference's status
    When an editor creates a Story from the Reference
    Then the Reference's status is still pending

  Scenario: A rejected Reference stays rejected
    Given the Reference is rejected
    When an editor creates a Story from the Reference
    Then the Reference's status is still rejected

  Scenario: Tapping again offers the existing Story and makes no duplicate
    Given an editor created a Story from the Reference
    When the editor creates a Story from the Reference again
    Then no second Story is made
    And the existing Story is offered

  Scenario: A second Story is made only on purpose
    Given an editor created a Story from the Reference
    When the editor chooses to create another Story from the Reference
    Then a second Story is made with its own address

  Scenario: A summary that repeats the source's words is left out
    Given the Reference's generated summary repeats the source's own words
    When an editor creates a Story from the Reference
    Then the Story's body has no part of the source text
    And the Story's front matter says the summary was withheld

  Scenario: The section is set only when the site has exactly one
    Given the site has one section "analysis"
    When an editor creates a Story from the Reference
    Then the Story is in the section "analysis"

  Scenario: The idea pipeline does not draft a Reference that already has a Story
    Given the Reference is accepted
    When an editor creates a Story from the Reference
    Then the idea pipeline no longer offers the Reference as a single-item idea
