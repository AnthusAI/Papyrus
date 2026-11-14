@backend @idea-run-large-site
Feature: On a site with thousands of References one run reads what editors worked on and drafts from it
  A daily monitor-stories run has a time budget. On a site with a big backlog of imported References (Machines on Machines: about 1,400 accepted and 6,500
  pending), a run once spent its whole budget walking the index and the lists before it drafted, reported no candidates, and drafted nothing, even though an
  editor had voted on 30 References that day. A run now reads and drafts the References a person worked on first, does not count the pending backlog before it
  drafts, skips the References the index already holds when it walks the index, gives the vector pass and the signal reading a share of the time that cannot
  starve the drafting, and says in its log line how long each stage took.

  Scenario: The References an editor voted on are candidates even when the time stops the reading early
    Given a site with 6 accepted monitored References, the oldest of which an editor voted on
    When the time stops the reading after 2 References
    Then the voted Reference was read and is a candidate

  Scenario: A Reference an editor tagged or talked about is read before the bulk imports
    Given a site with 6 accepted monitored References, the oldest of which an editor tagged with a concept
    When the time stops the reading after 2 References
    Then the tagged Reference was read and is a candidate

  Scenario: Counting the pending backlog does not come before drafting
    Given a site with 6 accepted monitored References, the oldest of which an editor voted on
    When the candidates are collected without counting the pending References
    Then the pending References were not listed and there are 6 candidate Reference read

  Scenario: The index walk leaves out a Reference whose summary vector is already there with its current status
    Given an index that holds the summary vectors of the accepted Reference "one" and of "three", which was pending when it was indexed
    When the router's index sync walks the Reference "one", "two" and "three"
    Then only "two" and "three" are prepared
    And the sync counts 1 Reference skipped because it was indexed

  Scenario: A run whose vector pass and signal reading used their share still drafts, and its log line says how long each stage took
    Given a router publication whose entry names an index and a storage bucket
    And 2 accepted References that the "hn" monitor delivered, one accepted since the last pass
    And the vector pass's share of the time is already spent
    And the signal reading's share of the time is already spent
    When the router runs its daily monitor stories with the vector pass
    Then 2 ideas are drafted
    And the log line says how many seconds the vector pass, the signal reading, the drafting and the reading of candidates took

  Scenario: The router gives the vector pass a quarter, the signal reading a sixth and drafting the rest
    Given the router has 400 seconds left when a publication starts
    When the router runs its daily monitor stories with a fake drafter
    Then the vector pass is over below 330 seconds left, the signal reading below 283 and drafting below 120
