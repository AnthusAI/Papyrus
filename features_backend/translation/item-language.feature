Feature: Every Story version knows its language, and translations are sibling Stories joined by a language group
  A publication may tell one Story in several languages (docs/plans/multilingual-publishing.md). Each language is its own Story lineage, a
  sibling of the primary with its own versions, checklist and published row; the siblings are joined by a language group whose key is the
  primary Story's lineage id. A translation's lineage id is derived from its primary and its language (`story-rivers--zh-Hans`), so making
  it twice is the same record.

  Every Item version carries its `language` (a BCP 47 tag in Humanus's spelling: en, es-419, zh-Hans) and its `languageGroupId`. A version
  of a translation also says exactly which primary version it was translated from. Only the translation procedure writes a language other
  than the site's primary language, and it always names the language and the group; every other writer writes the primary language, and the
  authoring client fills that in, with the Story's own lineage as its group, on any Item written without them.

  Every writer goes through that one rule: `papyrus stories save-version`, the console's saves, the agent and ops procedures, `stories create`,
  the checklist's step rows and imports. A version written without a language takes the language of the version it follows, so a Story never
  changes language by being saved again; a Story with no earlier version starts in the primary language.

  Rows written before the fields existed, or by a Papyrus older than the release that added them, get them from `papyrus stories languages`. Nothing reads a missing language as the primary: the
  editorial checks refuse a saved Story version that has none and name the command.

  Background:
    Given the site writes in English, Latin American Spanish and Simplified Chinese, with English as its primary language

  Scenario: A new Story is written in the primary language and is its own language group
    Given an authoring client for the tenant "mom"
    When a writer creates the Story "story-rivers" without naming a language
    Then the Item written has the language "en"
    And its language group is "mom#story-rivers"

  Scenario: A new version keeps the language and group of the version it follows
    Given an authoring client for the tenant "mom"
    And the Story "story-rivers--zh-Hans" is stored in "zh-Hans" in the language group "mom#story-rivers"
    When a writer saves the Story "story-rivers--zh-Hans" again without naming a language
    Then the Item written has the language "zh-Hans"
    And its language group is "mom#story-rivers"

  Scenario: A version saved with the command line is written in the primary language and can be published
    Given an authoring client for the tenant "mom"
    And the Story "story-rivers" has a saved version with no language, written by a Papyrus older than the language fields
    When an editor saves a new version of the Story "story-rivers" with `papyrus stories save-version`
    Then the new version "story-rivers-v2" is written with the language "en" and the language group "mom#story-rivers"
    And the version can be published because its language is known

  Scenario: A version saved with the command line keeps the language of the Story it follows
    Given an authoring client for the tenant "mom"
    And the Story "story-rivers--zh-Hans" is stored in "zh-Hans" in the language group "mom#story-rivers"
    When an editor saves a new version of the Story "story-rivers--zh-Hans" with `papyrus stories save-version`
    Then the new version "story-rivers--zh-Hans-v2" is written with the language "zh-Hans" and the language group "mom#story-rivers"

  Scenario: A version written without a language takes the language of the version it follows
    Given an authoring client for the tenant "mom"
    And the Story "story-rivers--zh-Hans" is stored in "zh-Hans" in the language group "mom#story-rivers"
    When a writer creates the version "story-rivers--zh-Hans-v2" of the Story "story-rivers--zh-Hans" following "story-rivers--zh-Hans-v1" without naming a language
    Then the Item written has the language "zh-Hans"
    And its language group is "mom#story-rivers"

  Scenario: A checklist step version is written with a language too
    Given an authoring client for the tenant "mom"
    When the checklist writes the second version of the step "step-story-rivers-illustration" of the Story "story-rivers"
    Then the step version "step-story-rivers-illustration-v2" is written with the language "en"

  Scenario: A translation must name its language group
    Given an authoring client for the tenant "mom"
    When a writer creates the Story "story-rivers--es-419" in "es-419" without a language group
    Then the write is refused because a translation names the primary Story's lineage as its language group
    And no Item was sent to the data API

  Scenario: A translation's lineage is derived from its primary and its language
    Then the translation of "story-rivers" into "zh-Hans" has the lineage "story-rivers--zh-Hans"

  Scenario: A Story whose own lineage id contains the separator has derived translations too
    The ids the site generates for a Story with a long headline end in a hash after the separator, and such a Story is an ordinary primary Story.
    Whether a row is a translation is read from its language group, never from the shape of its id.
    Then the translation of "content-item-a-florida-deputy-used-police-databases-and-plate-readers-to--bde88a5abce21df8" into "es-419" has the lineage "content-item-a-florida-deputy-used-police-databases-and-plate-readers-to--bde88a5abce21df8--es-419"
    And the translation of "content-item-a-florida-deputy-used-police-databases-and-plate-readers-to--bde88a5abce21df8" into "zh-Hans" has the lineage "content-item-a-florida-deputy-used-police-databases-and-plate-readers-to--bde88a5abce21df8--zh-Hans"
    And the translation of "item-agents-shopify-sidekick-prompt-compression" into "zh-Hans" has the lineage "item-agents-shopify-sidekick-prompt-compression--zh-Hans"

  Scenario: The derived id is one-to-one, so a language is never read out of a primary's id
    Then the lineage "content-item-a-free-driving-game-demo-ran-up-a-1-000-a-day-ai-bill-d5d5f549b245433e--es-419" is the translation into "es-419" of "content-item-a-free-driving-game-demo-ran-up-a-1-000-a-day-ai-bill-d5d5f549b245433e" and of nothing else
    And the lineage "content-item-a-free-driving-game-demo-ran-up-a-1-000-a-day-ai-bill-d5d5f549b245433e" is not a translation of anything
    And a language tag containing the separator is refused

  Scenario: A translation is recognised by its row, not its id, and cannot itself be translated
    Then the row of "story-rivers--zh-Hans" in the group "mom#story-rivers" is a translation of "story-rivers"
    And the row of "content-item-a-florida-deputy-used-police-databases-and-plate-readers-to--bde88a5abce21df8" in its own group is not a translation
    And asking to translate the translation "story-rivers--zh-Hans" is refused, naming the original "story-rivers"

  Scenario: The members of a language group in one language are one index query
    Given the Story "story-rivers" in "en" and its translations into "es-419" and "zh-Hans"
    When the language group "story-rivers" is read for "zh-Hans"
    Then only the rows of "story-rivers--zh-Hans" are returned
    And they were read with one query on the language group index

  Scenario: The editorial checks read the Story's own language
    Given a saved Story version in "zh-Hans"
    Then the language the checks use for it is "zh-Hans"
    And a Story not saved yet is checked in "en"

  Scenario: A saved version without a language is refused, never read as the primary
    Given a saved Story version with no language
    Then asking its language is refused, naming "papyrus stories languages"

  Scenario: The backfill gives every older row the primary language and its own lineage as its group
    Given three Item rows written before the language fields existed, one of them superseded
    And one row of the Story "story-old--zh-Hans" already stored in "zh-Hans" in the group "story-old"
    When the operator backfills the languages with "papyrus stories languages"
    Then the three older rows have the language "en" and their own lineage as their group
    And each keeps its own update time
    And the "zh-Hans" row is not written
    And the rows were read through the version-state index, with no table scan
    And the summary says "rows to write 3"

  Scenario: The backfill gives every older published row the language and group the projection serves it by
    Given three Item rows written before the language fields existed, one of them superseded
    And two published rows written before the language fields existed
    And the published row of "story-old--zh-Hans" already in "zh-Hans" in the group "story-old"
    When the operator backfills the languages with "papyrus stories languages"
    Then the two older published rows have the language "en" and their own lineage as their group
    And the translated published row is not written
    And the published summary says "rows to write 2"

  Scenario: Running the backfill again writes nothing
    Given three Item rows written before the language fields existed, one of them superseded
    When the operator backfills the languages with "papyrus stories languages"
    And the operator backfills the languages again
    Then the second backfill wrote no row
    And the summary says "rows to write 0"

  Scenario: A dry run of the backfill writes nothing
    Given three Item rows written before the language fields existed, one of them superseded
    When the operator previews the language backfill with "--dry-run"
    Then the backfill wrote no row
    And it printed one "would write" line per older row
