Feature: The router can deliver to every configured publication's API
  The monitoring router signs its AppSync calls with its own role, and IAM grants them per API id and per field. A publication whose
  backend has no grants cannot receive its References, decision relations, automatic acceptances or stories, however its router
  config reads. While one backend replaces another, both keep their grants until the old one is retired.

  Scenario: Every publication API in the monitoring stack has the router's delivery grants
    Given the monitoring stack template with its publication API parameters
    When the grants on the router role are listed per API
    Then every publication API has the intake, decision relation, automatic acceptance and enrichment read-back fields
    And Machines on Machines is granted alongside the Papyrus product-site backend it replaces
    And no managed policy was added to the router role and none exceeds its size limit
