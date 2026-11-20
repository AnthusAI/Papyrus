Feature: A backend deploy gives older rows their language before anything reads one
  Every Story version and every published row carries its language and its language group. The projection refuses a published row without a
  language, and the editorial checks refuse a Story without one, because nothing may read a missing language as English. Rows written before the
  fields existed have none. So the deploy that brings those readers writes the missing fields itself, inside the post-deploy render and before it:
  the site's primary language, and each Story's own lineage as its group, only where missing, keeping each row's own update time. It runs once per
  site. Nobody has to run a command by hand, and the rule stays strict for any row written afterwards.

  Background:
    Given a site whose Stories and published pages were all written before rows carried a language

  Scenario: The site deploys and projects with no manual step
    When the backend is deployed
    Then every Item row has the language "en" and its own lineage as its group
    And every published row has the language "en" and its own lineage as its group
    And each row keeps its own update time
    And every published page was rendered

  Scenario: The rows are written before the render or the editorial policies read anything
    When the backend is deployed
    Then the steps ran in the order: languages written, editorial policies, render

  Scenario: The published rows are found by their lineage, with no table scan
    When the backend is deployed
    Then the Items were read through the version-state index and each published row by its id
    And no checklist step was looked up as a published row

  Scenario: A second deploy reads one marker and writes nothing
    Given the backend was deployed once
    When the backend is deployed again
    Then no row was written
    And the language step read only its marker

  Scenario: A site that never set its languages gets English
    Given the site's editorial settings have no languages
    When the backend is deployed
    Then every Item row has the language "en" and its own lineage as its group

  Scenario: A site whose primary language is Spanish gets Spanish
    Given the site's primary language is "es-419"
    When the backend is deployed
    Then every Item row has the language "es-419" and its own lineage as its group

  Scenario: A step that fails part-way fails the deploy before the render, and the next deploy finishes
    Given writing the third row fails once
    When the backend is deployed and the deploy fails
    Then nothing was rendered and no page of the site changed
    And no marker was left
    When the backend is deployed
    Then every Item row has the language "en" and its own lineage as its group
    And every published page was rendered

  Scenario: A row written after the deploy without a language is still refused
    Given the backend was deployed once
    When a published row without a language is written later
    And that Story is projected
    Then the late projection is refused naming "papyrus stories languages"
    And a later deploy does not write it
