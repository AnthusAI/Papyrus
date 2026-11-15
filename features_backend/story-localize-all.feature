Feature: A whole site is translated by one command, and only what remains is done
  `papyrus stories localize --all` finds every published Story written in the site's primary language that has no up-to-date translation in a language
  (or in every enabled language), runs the registered translation procedure for each, and prints one row per Story and language: saved, held, failed or
  up to date, with its cost. A translation is up to date when its desired-state record names this very text of the Story and its run finished: a
  held translation counts, because it waits for a person and not for a machine. The command reads the published summaries once and the desired-state records
  through their state index, never a table per Story, and never runs a Story that is already done, so running it again does only what remains.

  A failure is that Story's row and nothing else: the other Stories go on, and the command exits with a failure that says to run it again. With
  `--publish-clean` the translations whose run saved cleanly are published through the ordinary publish path, and nothing else is: never a held
  translation, never one whose original is no longer published at the text it was translated from, never one in a language the site does not
  write in. A dry run predicts each Story's cost from the measured runs of the procedure and writes nothing. With `--automation` the command only queues
  the work for the site's own runner (the dispatcher of translate on publish) and nothing waits.

  On a tenant backend (every Papyrus site) a published row stores its language group with the tenant's prefix (`machines-on-machines#story-a`) while
  the Story's lineage and the desired-state records use the bare lineage; the survey compares them with the prefix removed.

  Background:
    Given a site written in "en" that also writes in "es-419"
    And the published English Stories "story-a", "story-b", "story-c", "story-d" and "story-e"
    And "story-a" has a saved Spanish translation of its published text
    And "story-c" has a Spanish request for an older text
    And "story-d" has a Spanish translation that is held
    And "story-e" is marked do not localize

  Scenario: The command finds exactly the Stories with no up-to-date translation
    When the whole site is surveyed for "es-419"
    Then "story-a" is up to date
    And "story-b" is to do because nothing was ever requested
    And "story-c" is to do because its request is for older text
    And "story-d" is up to date, held for a person
    And "story-e" is not listed
    And the Spanish translations themselves are not listed as Stories to translate
    And the survey read the published summaries once and the requests through their state index, never a table per Story

  Scenario: Stories whose stored language group carries the tenant prefix are found
    Given the stored language group of every published row is the tenant prefix and the Story's lineage
    When the whole site is surveyed for "es-419"
    Then "story-b" is to do because nothing was ever requested
    And "story-a" is up to date
    And "story-b" is listed exactly once

  Scenario: A held translation is held whatever its request record says, and is never planned again
    A held translation waits for a person. The request record is where its run is meant to say so, but a run can end after saving the translation and before
    writing that, and the record can be written again for the same text. The translation itself says which text it was made from and that it is held, so the
    survey believes it, reports it held and leaves the record and the translation alone: a new run could replace what a person has yet to answer.
    Given the published English Stories "story-f" and "story-g"
    And "story-f" has a Spanish translation that is held, though its request says only that a run started
    And "story-g" has a Spanish translation that is held, though its request was written again and not yet run
    When the whole site is planned for "es-419"
    Then "story-f" is up to date, held for a person, and its request record is left as it was
    And "story-g" is up to date, held for a person, and its request record is left as it was
    And "story-f" and "story-g" are not run

  Scenario: A run that failed is remaining work, and one that is still going is not
    Given the Spanish request for "story-b" names this text and its run failed
    And the Spanish request for "story-c" names this text and its run is queued on an automation
    When the whole site is surveyed for "es-419"
    Then "story-b" is to do, with the reason its last run gave
    And "story-c" is queued

  Scenario: Every remaining Story is run, failures are isolated and the rows are printed
    Given the translation of "story-c" fails in the model service
    When the whole site is translated in this process for "es-419"
    Then "story-b" is saved with its cost
    And "story-c" is failed, saying the model service could not be reached
    And "story-a" and "story-d" are not run
    And the table has one row for each of the four Stories and a totals row

  Scenario: Running it again does only what remains
    Given the whole site was translated in this process for "es-419", and "story-c" failed
    When the whole site is translated in this process for "es-419" again
    Then only "story-c" is run

  Scenario: Clean translations are published and held ones are not
    Given the Spanish run of "story-b" saves cleanly and the Spanish run of "story-c" is held
    When the whole site is translated in this process for "es-419" with --publish-clean
    Then the Spanish translation of "story-b" is published through the ordinary publish path
    And the Spanish translation of "story-c" is not published and its row says a person answers its review request
    And the Spanish translation of "story-d", which was already held, is not published

  Scenario: A translation saved earlier and never published is published by --publish-clean
    When the whole site is translated in this process for "es-419" with --publish-clean
    Then the Spanish translation of "story-a" is published through the ordinary publish path

  Scenario: A translation of older text is never published: the Story is translated again and that is published
    Given "story-a" was published again after its translation was saved
    When the whole site is translated in this process for "es-419" with --publish-clean
    Then "story-a" is run again for its new text
    And the Spanish translation published for "story-a" is the one of its new text

  Scenario: A dry run predicts the cost and writes nothing
    Given the procedure has measured Spanish runs
    When the whole site is planned for "es-419"
    Then the plan lists "story-b" and "story-c" with a predicted cost each
    And no request, translation or publish was written

  Scenario: A language with no measured run has no prediction, and says so
    When the whole site is planned for "es-419"
    Then the rows to do say that no run of the language has been measured

  Scenario: With an automation the work is queued for the site's runner
    When the whole site is queued on the automation "mom.story-localize" for "es-419" with --publish-clean
    Then the Spanish requests of "story-b" and "story-c" are wanted, name that automation and ask for a clean result to be published
    And no procedure was run here

  Scenario: A Story whose lineage id contains the separator is surveyed and planned like any other
    The ids the site gives a Story with a long headline end in a hash after a double hyphen. Such a Story is a primary Story: its translation is
    the same id with the language after one more double hyphen, and neither the survey nor the plan treats it as anything else.
    Given the published English Story "content-item-a-florida-deputy-used-police-databases-and-plate-readers-to--bde88a5abce21df8" at its first text
    And the procedure has measured Spanish runs
    When the whole site is planned for "es-419"
    Then "content-item-a-florida-deputy-used-police-databases-and-plate-readers-to--bde88a5abce21df8" is to do because nothing was ever requested
    And "content-item-a-florida-deputy-used-police-databases-and-plate-readers-to--bde88a5abce21df8" has a predicted cost and no reason it cannot be planned

  Scenario: Every enabled language is covered by --all-languages
    Given the site also writes in "zh-Hans"
    When the whole site is surveyed for every enabled language
    Then "story-b" is to do in "es-419" and in "zh-Hans"

  Scenario: The command prints a row for each Story and fails saying to run it again when one failed
    Given the translation of "story-c" fails in the model service
    When an operator signed in with AWS credentials runs "papyrus stories localize --all --language es-419"
    Then the output has a "saved" row for "story-b" and a "failed" row for "story-c" and a totals row
    And the command fails saying 1 of 4 translations failed and that running it again does only what remains

  Scenario: The command refuses a call it cannot do before it writes anything
    When an operator signed in with AWS credentials runs "papyrus stories localize --all --story story-b --language es-419"
    Then it is refused saying --all translates every Story
    When an operator signed in with AWS credentials runs "papyrus stories localize --all"
    Then it is refused saying --all needs exactly one of --language and --all-languages
    When an operator signed in with AWS credentials runs "papyrus stories localize --all --language en"
    Then it is refused saying en is the primary language
    When a person signed in without AWS credentials runs "papyrus stories localize --all --language es-419"
    Then it is refused naming the operator lane and --automation
    And no request was written by the command

  Scenario: The command's dry run prints the predicted cost and writes nothing
    Given the procedure has measured Spanish runs
    When an operator signed in with AWS credentials runs "papyrus stories localize --all --language es-419 --dry-run"
    Then the output ends with a plan line for 2 Stories to do
    And no request was written by the command

  Scenario: A plan reads what depends only on the section and the language once, and the request budget allows for the work
    A plan reads each Story's own text and translation, but the settings, the editing packs, the glossary and the register guidelines depend only on the site,
    the section and the language, so they are read once for the whole plan and shared by every Story. Each translation still to do is a unit of work in the
    command's request budget (200 plus 8 for each), so a plan of hundreds of Stories is not reported as a runaway loop.
    Given the procedure has measured Spanish runs
    When an operator signed in with AWS credentials runs "papyrus stories localize --all --language es-419 --dry-run"
    Then every Story of the plan was planned with the same shared reads
    And the request budget of the command allows for the 2 translations to do
