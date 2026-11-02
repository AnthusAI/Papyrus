Feature: The public wiki publishes the subjects of a publication and nothing else
  A publication's semantic graph holds more than its subjects. A site that was copied from
  another one brings the paper authors of that site, the editorial concepts its comments are
  filed under, quality ratings, relevance decisions, coverage questions and editorial forms,
  all accepted nodes. A wiki that publishes every accepted node puts that bookkeeping in
  front of readers. The wiki publishes the entity kinds of the site's vocabulary: the kinds
  the entity extraction is told to look for. The bookkeeping kinds are never public, whatever
  a vocabulary says, and paper authors are public only when the vocabulary names them.
  A name that arrived without spaces reads as a name on its page. When a kind leaves the
  vocabulary, the next run takes its pages down, so a run that finds a wiki with junk in it
  leaves a wiki without.

  Background:
    Given a graph with accepted entities "Acme Loom" (maker), "Beta Spool" (tool), "AaronCohen" (personAuthor), "General comment" (commentConcept) and "Five star quality" (qualityRating)

  Scenario: With no vocabulary the bookkeeping kinds and the paper authors get no page
    When the wiki sync runs with no vocabulary
    Then the wiki has pages for "Acme Loom" and "Beta Spool" only

  Scenario: A vocabulary names the only kinds that get a page
    When the wiki sync runs with a vocabulary of the kinds "maker"
    Then the wiki has pages for "Acme Loom" only

  Scenario: Paper authors are public when the vocabulary names them, and their names are spaced
    When the wiki sync runs with a vocabulary of the kinds "maker, personAuthor"
    Then the wiki has pages for "Acme Loom" and "Aaron Cohen" only
    And the page for "Aaron Cohen" keeps the entity key "personauthor--aaroncohen"

  Scenario: The bookkeeping kinds stay private even when a vocabulary names them
    When the wiki sync runs with a vocabulary of the kinds "maker, commentConcept, qualityRating"
    Then the wiki has pages for "Acme Loom" only

  Scenario: Names of companies and models are never respaced
    Given an accepted entity "DeepSeek" (organization)
    When the wiki sync runs with a vocabulary of the kinds "organization"
    Then the wiki has pages for "DeepSeek" only

  Scenario: Entity links in the knowledge snapshot go only to pages that exist
    When the knowledge snapshot is built with a vocabulary of the kinds "maker"
    Then "Acme Loom" links to its wiki page
    And "AaronCohen" has no link
    And the snapshot has no entity "General comment"

  Scenario: A kind that leaves the vocabulary has its live pages taken down
    Given the wiki was synced and published with a vocabulary of the kinds "maker, tool, personAuthor"
    When the wiki sync runs with a vocabulary of the kinds "maker, tool" and retiring
    Then the page for "Aaron Cohen" is no longer live and is marked retired
    And the pages for "Acme Loom" and "Beta Spool" are still live
    And the sync reports one page to remove from the site

  Scenario: A retired page is not published again by the next publish
    Given the wiki was synced and published with a vocabulary of the kinds "maker, tool, personAuthor"
    And the wiki sync ran with a vocabulary of the kinds "maker, tool" and retiring
    When every draft is published
    Then the page for "Aaron Cohen" is not live

  Scenario: Without the retire flag a page nothing generates any more is only reported
    Given the wiki was synced and published with a vocabulary of the kinds "maker, tool, personAuthor"
    When the wiki sync runs with a vocabulary of the kinds "maker, tool"
    Then the page for "Aaron Cohen" is still live
    And the sync warns that "Aaron Cohen" is no longer generated

  Scenario: A dry run says what it would retire and changes nothing
    Given the wiki was synced and published with a vocabulary of the kinds "maker, tool, personAuthor"
    When the wiki sync dry run is made with a vocabulary of the kinds "maker, tool" and retiring
    Then the dry run lists the page for "Aaron Cohen" as live and to be taken down
    And the page for "Aaron Cohen" is still live

  Scenario: A page that comes back into the vocabulary is a draft again and can be published
    Given the wiki was synced and published with a vocabulary of the kinds "maker, tool, personAuthor"
    And the wiki sync ran with a vocabulary of the kinds "maker, tool" and retiring
    When the wiki sync runs with a vocabulary of the kinds "maker, tool, personAuthor" and retiring
    And every draft is published
    Then the page for "Aaron Cohen" is live and not marked retired

  Scenario: A vocabulary with no entity kinds is refused rather than read as "everything"
    When the wiki sync runs with a vocabulary that declares no kinds
    Then the sync is refused because the vocabulary declares no entity kinds
