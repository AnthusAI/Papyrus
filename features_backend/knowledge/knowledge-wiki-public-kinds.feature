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

  Scenario: A concept an editor invented by typing a hashtag has no page until the vocabulary names its kind
    Given an accepted entity "Fake Website Networks" (editor_concept)
    When the wiki sync runs with no vocabulary
    Then the wiki has pages for "Acme Loom" and "Beta Spool" only

  Scenario: A vocabulary that names the kind publishes the editor's concept
    Given an accepted entity "Fake Website Networks" (editor_concept)
    When the wiki sync runs with a vocabulary of the kinds "maker, editor_concept"
    Then the wiki has pages for "Acme Loom" and "Fake Website Networks" only

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

  Scenario: A kind that leaves the vocabulary keeps its live pages
    A page that was ever public may be indexed by search engines, so the sync never takes one down.
    Taking a page down is a deliberate, redirecting act, never a side effect of a daily run.
    Given the wiki was synced and published with a vocabulary of the kinds "maker, tool, personAuthor"
    When the wiki sync runs with a vocabulary of the kinds "maker, tool"
    Then the page for "Aaron Cohen" is still live
    And the pages for "Acme Loom" and "Beta Spool" are still live
    And the sync warns that "Aaron Cohen" is no longer generated
    And the sync reports no page to take down

  Scenario: A publish after the kind left does not take the page down either
    Given the wiki was synced and published with a vocabulary of the kinds "maker, tool, personAuthor"
    And the wiki sync ran with a vocabulary of the kinds "maker, tool"
    When every draft is published
    Then the page for "Aaron Cohen" is still live and not marked retired

  Scenario: The sync no longer has a retire flag
    Given the wiki was synced and published with a vocabulary of the kinds "maker, tool, personAuthor"
    When the wiki sync dry run is made with a vocabulary of the kinds "maker, tool"
    Then the dry run changes nothing and lists no page to retire
    And the page for "Aaron Cohen" is still live

  Scenario: A page that an earlier version of the sync retired comes back as a draft when its kind returns
    Given the wiki was synced and published with a vocabulary of the kinds "maker, tool, personAuthor"
    And the page for "Aaron Cohen" was taken down and marked retired by an earlier version of the sync
    When the wiki sync runs with a vocabulary of the kinds "maker, tool, personAuthor"
    And every draft is published
    Then the page for "Aaron Cohen" is live and not marked retired

  Scenario: A vocabulary with no entity kinds is refused rather than read as "everything"
    When the wiki sync runs with a vocabulary that declares no kinds
    Then the sync is refused because the vocabulary declares no entity kinds

  Scenario: A wiki page that places knowledge blocks passes the publish check
    When the wiki sync runs with a vocabulary of the kinds "maker, tool"
    Then the publish check passes for the page "Acme Loom"

  Scenario: A page that places an include the site does not know is refused by name
    When the wiki sync runs with a vocabulary of the kinds "maker, tool"
    And the page "Acme Loom" places an include the site does not know
    Then the publish check refuses the page "Acme Loom" by name and says nothing was published

  Scenario: A publish whose page could not be projected says so and how to retry
    Given the wiki was synced with a vocabulary of the kinds "maker, tool"
    When every draft is published and the site fails to project the pages
    Then the publish report names the unprojected page and gives the retry command
    And the page "Acme Loom" is live
