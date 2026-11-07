@backend @batched-reads
Feature: Reads for many rows ride in one AppSync request, 25 to a request, and return what the one-at-a-time reads return
  AppSync bills per request. A loop that reads one row, or one index partition, for each of a hundred References costs a hundred
  requests; the same reads sent as GraphQL aliases cost four. The Python client sends gets by id and index queries 25 to a request,
  finishes any partition that has a second page on its own so every list is complete, applies the tenant rule to each row, and
  treats a missing row as missing. Looking up many ids never reads the whole table, however many there are. Automatic acceptance
  reads the Cyclotron's verdicts for 25 References per request, and the router reads the References of its prediction requests
  the same way; what they decide does not change. Nothing here touches AWS: the backend is a fake that counts requests.

  Scenario: Sixty ids are read in three requests
    Given 60 References and 1 id that does not exist
    When the client gets them all by id
    Then 3 requests were made
    And the 60 References come back and the missing one does not

  Scenario: Looking up more than 100 ids never lists the whole table
    Given 240 References
    When the client gets them with get_records_by_id
    Then 10 requests were made and none of them listed every Reference

  Scenario: Index partitions are read 25 keys to a request and a long partition is finished
    Given 53 partitions of relations and one partition with 7 relations, read 3 to a page
    When the client reads the partitions together
    Then each partition returns the same rows as reading it alone
    And the long partition returns all 7 relations

  Scenario: An aliased request counts as one request in the meter
    Given 25 References
    When the client gets them all by id inside a metered run
    Then the run counted 1 request that folded 25 reads

  Scenario: An automatic acceptance pass costs one request per 25 References
    Given a publication whose editors voted on 60 References and has 10 waiting
    And another whose editors voted on 600 and has 100 waiting
    When automatic acceptance runs on each as a dry run
    Then each pass made its index reads, plus one request per 25 voted References and one per 25 waiting ones
    And both passes decided the same way as the per-Reference pass: every vote counted, every waiting confident Reference a candidate
