Feature: A knowledge run shows a person its bulk writes before they go live
  On 2026-11-02 a knowledge run published 1,366 wiki pages nobody had looked at, most of them
  bookkeeping and paper authors. The stage that writes pages now plans first. A site's first
  run is a preview: the counts by kind and a sample wait in the Notification Center as a hard
  gate, and nothing is written until a person accepts it. A later run goes through unless its
  output differs sharply from that site's own earlier runs, judged against what those runs
  show and not against a fixed number. A held run writes nothing, its execution does not
  project, and the plan it made is kept. Accepting the request is done in the console or with
  the signed-in papyrus command, and needs no AWS login: the next run reads the answer
  through the site's data API. Only a person's acceptance counts.

  Background:
    Given a publication whose knowledge run is on its stage "wiki-sync"

  Scenario: A first run that would write pages is held and writes nothing
    When execution "run-1" plans 40 "personauthor" pages and 3 "maker" pages
    Then the stage held the run and wrote no page
    And the Notification Center holds one hard gate that says nothing has been written
    And the gate lists "entity/personauthor:create 40" and a sample of the page titles
    And the plan is kept in the run's state

  Scenario: A held execution does not project the site
    When execution "run-1" plans 3 "maker" pages
    And the stage "projection" runs in the held execution
    Then nothing was projected

  Scenario: A run that would write nothing is never held
    When execution "run-1" has nothing to write
    Then the stage wrote its pages and raised no request

  Scenario: The same plan waits on one request, and goes through after a person accepts it
    Given execution "run-1" plans 12 "maker" pages
    When execution "run-2" plans 12 "maker" pages
    Then the stage held the run and wrote no page
    And there is still only one request
    When a person accepts the request
    And execution "run-3" plans 12 "maker" pages
    Then the stage wrote its pages and published them

  Scenario: A rejected plan stays held and nobody is asked again
    Given execution "run-1" plans 12 "maker" pages
    When a person rejects the request
    And execution "run-2" plans 12 "maker" pages
    Then the stage held the run and wrote no page
    And there is still only one request

  Scenario: An agent's answer does not open the gate
    Given execution "run-1" plans 12 "maker" pages
    When an agent accepts the request
    And execution "run-2" plans 12 "maker" pages
    Then the stage held the run and wrote no page

  Scenario: After an accepted first run a similar run goes through
    Given execution "run-1" plans 20 "maker" pages
    And a person accepts the request
    When execution "run-2" plans 22 "maker" pages
    Then the stage wrote its pages and published them

  Scenario: After an accepted first run a surge of another kind is held with what history predicted
    Given execution "run-1" plans 20 "maker" pages
    And a person accepts the request
    When execution "run-2" plans 22 "maker" pages and 900 "personauthor" pages
    Then the stage held the run and wrote no page
    And the request says "entity/personauthor:create would write 900" and that it is unlike this site's earlier runs

  Scenario: What is normal is learned from the site's own runs
    Given the site wrote 5, 60, 10, 80, 15 and 55 "maker" pages in its earlier runs
    When execution "next" plans 70 "maker" pages
    Then the stage wrote its pages and published them

  Scenario: The same count is a surge for a site whose runs are steady
    Given the site wrote 20, 20, 20, 20, 20 and 20 "maker" pages in its earlier runs
    When execution "next" plans 70 "maker" pages
    Then the stage held the run and wrote no page

  Scenario: A hold nobody could see fails the stage so the alarm reaches a person
    Given the site's data API cannot be reached
    When execution "run-1" plans 12 "maker" pages
    Then the stage failed and wrote no page
