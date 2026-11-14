@checklist-gate
Feature: A translation is published as a person's act, with its own gates, and its page says what it is
  The Story translation procedure (`papyrus.story.localize`) saves each translation as an unpublished version of the Story's sibling lineage
  (`<story>--<language>`). A person publishes it through the ordinary publish path (`papyrus ops content publish`, or the console), and the site
  serves it under its language's prefix with its own address. Nothing publishes by itself.

  A translation is not written the way an English Story is, so its checklist is its provenance: the run that saved it proves that it was translated,
  checked against the English and copy edited, and nothing has to be ticked by hand. It has two gates. A translation the procedure held (a finding
  that changes the meaning remains, or the run's cost reached its ceiling) publishes only after a person clears the review request the run raised.
  And it publishes only while its original is published: the page is served beside the original's, so taking the original down takes the
  translation off the site, and publishing it again brings the translation back. A translation has no rating of its own; one rating serves every
  language of a Story, and a machine never creates one.

  Every translated page says, in its own language and apart from the Story's text, that an AI translated it from the English original, with a link
  to the original. Agents read the same facts in the page's JSON-LD and in its Markdown twin. Everything here is synthetic: the models are scripted
  and nothing reaches a network.

  Background:
    Given the published English Story "story-waymo" version 3 in the Machines on Machines newsroom
    And a scripted translator, judge and repairer for "es-419"
    And an editor asked for the "es-419" translation of "story-waymo"
    And the English Story is served by a site that publishes Spanish under "es"

  Scenario: A clean translation is published under /es/ with its own address and its label
    Given the translation run for "es-419" has finished
    When a person publishes the translation
    Then the translation is published as "story-waymo--es-419" at "es/articles/bajan-los-choques-de-waymo/index.html"
    And the Spanish page says "Traducido por IA del original en inglés" and links the English page
    And the Story's own text does not contain "Traducido por IA"
    And the Waymo English page lists hreflang "en" and "es-419" and x-default pointing at itself
    And the English listings do not list the translation
    And the translation has no checklist steps and no rating of its own

  Scenario: An agent reads the same facts from the page
    Given the translation run for "es-419" has finished
    When a person publishes the translation
    Then the Spanish page's JSON-LD says inLanguage "es-419" and is a translationOfWork of the English page in "en"
    And the Spanish Markdown twin says language "es-419", translation "machine" and the English page it was translated from

  Scenario: A held translation does not publish until a person clears it
    Given the translator writes "varias ciudades" where the English says "12 cities"
    And the repairer keeps the wrong wording
    And the translation run for "es-419" has finished held
    When a person publishes the translation
    Then publishing is refused as "translation-held" naming the review request
    And no Spanish page is served
    When a person answers the review request with "approve"
    And a person publishes the translation
    Then the translation is published as "story-waymo--es-419" at "es/articles/bajan-los-choques-de-waymo/index.html"

  Scenario: A person who rejects the held translation keeps it back
    Given the translator writes "varias ciudades" where the English says "12 cities"
    And the repairer keeps the wrong wording
    And the translation run for "es-419" has finished held
    When a person answers the review request with "reject"
    And a person publishes the translation
    Then publishing is refused as "translation-held" naming the review request
    And no Spanish page is served

  Scenario: A held translation never holds the English Story
    Given the translator writes "varias ciudades" where the English says "12 cities"
    And the repairer keeps the wrong wording
    And the translation run for "es-419" has finished held
    Then the Waymo English page is published and has no Spanish alternate
    And no review request is about the English Story

  Scenario: A translation is published only while its original is
    Given the translation run for "es-419" has finished
    And the English Story is taken down
    When a person publishes the translation
    Then publishing is refused as "original-unpublished" naming "story-waymo"
    And no Spanish page is served

  Scenario: Unpublishing the translation takes its page away and updates the English page
    Given the translation run for "es-419" has finished
    And a person publishes the translation
    When a person unpublishes the translation
    Then no Spanish page is served
    And the Waymo English page lists no hreflang links
    And the Waymo English page is still published

  Scenario: Taking the original down takes the translation off the site, and publishing it again brings it back
    Given the translation run for "es-419" has finished
    And a person publishes the translation
    When the English Story is taken down
    Then no Spanish page and no Spanish listing is served
    And the translation's own record is still published
    When the English Story is published again
    Then the Spanish page is back at "es/articles/bajan-los-choques-de-waymo/index.html"
    And the Waymo English page lists hreflang "en" and "es-419" and x-default pointing at itself

  Scenario: Publishing a translation announces nothing to the English subscribers
    Given the translation run for "es-419" has finished
    When a person publishes the translation
    Then the new-story alert for the translation is ignored as a translation
    And the roundup of the week names the English Story and not the translation

  Scenario: A public language needs the words of the translation line, with a place for the link
    Given the Spanish interface strings lack "translation.label"
    When the multilingual site is projected
    Then the projection is refused naming "es-419: translation.label"

  Scenario: A translation line with no place for the link to the original is refused
    Given the Spanish translation line is "Traducido por IA"
    When the multilingual site is projected
    Then the projection is refused naming "translation.label (it must contain {original})"
