Feature: A published Story is translated and published by the site's own runner
  A site can turn on translate on publish: the editorial check settings' `languages.auto` names the Automation that runs the registered translation
  procedure and whether clean results publish. It is off by default and changes nothing on a site that never turns it on.

  When a Story written in the primary language is published, or published again with new text, the publish path writes one desired-state record
  (`LocalizationRequest`) for each enabled language other than the primary: the newest published source version, the automation, and the publish choice.
  That is the whole trigger, and it is durable: the record exists whatever happens next. A record already naming the same text asks for nothing again,
  a newer publish overwrites the older record, and a translation is never itself translated.

  The site's dispatcher reacts to those records on the site's own runner. It starts each waiting run through the automation (the same code as Run now,
  so the automation's limits and the router's model key apply), claims a record before invoking its run so overlapping batches never start one twice,
  leaves the rest waiting when the automation is at its limit and starts them when a run ends. When a run saves its translation cleanly and the record
  asks for it, the dispatcher has the content-actions function publish it through the ordinary path; a held translation is never published, and raises
  the review request it always did. Whether a published translation gets a page is still the language's public gate.

  Background:
    Given a site written in "en" with the further languages "es-419" and "zh-Hans"
    And the published English Story "story-a" at its first text

  Scenario: Translate on publish is off unless the site turns it on
    Given the site has not turned on translate on publish
    When "story-a" is published
    Then no translation request is written

  Scenario: Publishing a Story requests every enabled language
    Given the site turned on translate on publish with the automation "mom.story-localize" and publishing clean translations
    When "story-a" is published
    Then requests exist for "es-419" and "zh-Hans" naming source version 1, the automation "mom.story-localize" and the publish choice
    And both requests are wanted
    And no model was called and no run was started

  Scenario: The same text is requested once
    Given the site turned on translate on publish with the automation "mom.story-localize" and publishing clean translations
    And "story-a" was published and its translations requested
    When the publish of "story-a" is announced again
    Then no request was written again

  Scenario: Publishing new text overwrites the request, so there is one request per language
    Given the site turned on translate on publish with the automation "mom.story-localize" and publishing clean translations
    And "story-a" was published and its translations requested
    When "story-a" is published again with new text
    Then there is one request per language and each names source version 2

  Scenario: A request whose run failed is asked for again when the text is published again unchanged
    Given the site turned on translate on publish with the automation "mom.story-localize" and publishing clean translations
    And "story-a" was published and its translations requested
    And the "es-419" run failed
    When the publish of "story-a" is announced again
    Then the "es-419" request is wanted again and the "zh-Hans" request is left alone

  Scenario: A translation, a Story in another language and a Story marked do not localize are not requested
    Given the site turned on translate on publish with the automation "mom.story-localize" and publishing clean translations
    When a translation of "story-a" is published
    And a Story written in "es-419" is published
    And a Story marked do not localize is published
    Then no translation request is written

  Scenario: The dispatcher starts the waiting runs through the automation
    Given the site turned on translate on publish with the automation "mom.story-localize" and publishing clean translations
    And "story-a" was published and its translations requested
    When the dispatcher sees the new requests
    Then a run of "mom.story-localize" is started for each of the two languages, with the Story, the language and the source version
    And each request is started, not wanted

  Scenario: Overlapping batches never start one run twice
    Given the site turned on translate on publish with the automation "mom.story-localize" and publishing clean translations
    And "story-a" was published and its translations requested
    When two dispatcher batches see the same requests
    Then each language has exactly one run

  Scenario: An automation at its limit leaves the rest waiting until a run ends
    Given the site turned on translate on publish with the automation "mom.story-localize" and publishing clean translations
    And the automation allows one run at a time
    And "story-a" was published and its translations requested
    When the dispatcher sees the new requests
    Then one language is started and the other is still wanted
    When the dispatcher sees the started run end saved
    Then the other language is started

  Scenario: The dispatcher's own put-back does not wake it
    Given the site turned on translate on publish with the automation "mom.story-localize" and publishing clean translations
    And the automation allows one run at a time
    And "story-a" was published and its translations requested
    And the dispatcher saw the new requests
    When the dispatcher sees the change that put the waiting request back
    Then it starts nothing and reads nothing

  Scenario: A request that names no automation is a person's run and is left alone
    Given a person asked for the "es-419" translation of "story-a" from the command line
    When the dispatcher sees the new request
    Then no run is started and the request is unchanged

  Scenario: A request naming an automation that does not exist fails with the reason
    Given the site turned on translate on publish with the automation "mom.missing" and publishing clean translations
    And "story-a" was published and its translations requested
    When the dispatcher sees the new requests
    Then both requests are failed, saying the automation does not exist

  Scenario: A clean translation is published when the record asks for it
    Given the site turned on translate on publish with the automation "mom.story-localize" and publishing clean translations
    And "story-a" was published and its translations requested
    When the "es-419" run saves its translation cleanly
    And the dispatcher sees the request become saved
    Then the content-actions function is asked to publish the "es-419" translation
    And the "zh-Hans" translation is not asked for

  Scenario: A site that saves translations for a person to publish publishes nothing itself
    Given the site turned on translate on publish with the automation "mom.story-localize" and saving translations for a person to publish
    And "story-a" was published and its translations requested
    When the "es-419" run saves its translation cleanly
    And the dispatcher sees the request become saved
    Then the content-actions function is not asked to publish anything

  Scenario Outline: What may be published is decided in one place
    Given the site turned on translate on publish with the automation "mom.story-localize" and publishing clean translations
    And "story-a" was published and its translations requested
    And the "es-419" translation <situation>
    When the publishable translation is asked for
    Then the answer is <answer>

    Examples:
      | situation                                               | answer                                              |
      | was saved cleanly from this text                        | ready to publish                                    |
      | was held                                                | not publishable, waiting for a person               |
      | was saved cleanly and is already live at this text      | already published                                   |
      | was saved cleanly but the site stopped writing in it    | not publishable, the site does not write in it      |
      | was saved cleanly but the Story was published again     | not publishable, the original has moved on          |
      | was saved cleanly but the Story is no longer published  | not publishable, the original is not published     |

  Scenario: The publish funnel asks for translations and a failure to ask never fails the publish
    Given the site turned on translate on publish with the automation "mom.story-localize" and publishing clean translations
    When the content-actions function finds that "story-a" is live
    Then no other function is told
    And requests exist for "es-419" and "zh-Hans" naming source version 1, the automation "mom.story-localize" and the publish choice
    When the translation requests cannot be written and the function finds that "story-a" is live
    Then the failure is logged with its cause and the publish stands

  Scenario: The publish task publishes a clean translation through the console's publish and records it
    Given the site turned on translate on publish with the automation "mom.story-localize" and publishing clean translations
    And "story-a" was published and its translations requested
    And the "es-419" translation was saved cleanly from this text
    When the content-actions function runs the publish task for the "es-419" request
    Then the translation is published by "AI (translation on publish)" through the ordinary publish path
    And the "es-419" request is published

  Scenario: A refusal of the publish is written on the request and not retried
    Given the site turned on translate on publish with the automation "mom.story-localize" and publishing clean translations
    And "story-a" was published and its translations requested
    And the "es-419" translation was saved cleanly from this text
    And the site requires a person's approval to publish
    When the content-actions function runs the publish task for the "es-419" request
    Then the task answers that nothing was published, with the reason
    And the "es-419" request keeps its state and says why it was not published

  Scenario: The publish task does nothing for a held translation or a request that does not ask to publish
    Given the site turned on translate on publish with the automation "mom.story-localize" and saving translations for a person to publish
    And "story-a" was published and its translations requested
    And the "es-419" translation was saved cleanly from this text
    When the content-actions function runs the publish task for the "es-419" request
    Then the task answers that nothing was published, with the reason
    And nothing was published
