Feature: The router's configuration is files in Git, written to the monitoring table by the stack deploy
  A monitor's router config is one JSON file in infra/monitoring/router-config, named for the monitor (the hn monitor's, which holds the site publications, comes first; other monitors join by adding a file). The papyrus-monitoring stack runs a custom
  resource that writes the files to the table on each release, with its own narrow role, so nothing is seeded by hand and no deploy role changes.
  A site's automations (Run now, translate on publish, Stage Bots) start only when the site's router publication names the SSM parameter of its model key.

  Scenario: Every router config file is one the router accepts
    Given the router config files in Git
    Then every file passes the router's own validator
    And every file is named for its monitor
    And no file holds an AWS account id, an endpoint host or a Cyclotron id, only references

  Scenario: Every site publication on the hn router can start automations
    Given the router config files in Git
    Then each of the six site publications on the hn router names its model key parameter

  Scenario: Machines on Machines can be started by an automation
    Given the router config files in Git
    When they are applied to an empty monitoring table
    Then the automations code finds the Machines on Machines publication with a model key parameter and an endpoint

  Scenario: Applying twice writes once
    Given the router config files in Git
    When they are applied to an empty monitoring table
    And they are applied again
    Then the second apply writes nothing

  Scenario: A change in a file replaces the stored item whole
    Given the router config files in Git
    And the table holds an hn router config with a field typed by hand
    When they are applied
    Then the hn item equals its file and the hand-typed field is gone

  Scenario: A monitor with no file is left alone
    Given the router config files in Git
    And the table holds a router config for a monitor that has no file
    When they are applied
    Then that item is unchanged

  Scenario: A file the router would refuse fails the deploy before anything is written
    Given a router config file with a procedure trigger and no model key parameter
    When the stack deploy applies it
    Then the custom resource reports failure naming the file
    And no router config item is written

  Scenario: A reference that does not resolve fails the deploy
    Given the router config files in Git
    And the Cyclotron run id parameter does not exist
    When the stack deploy applies them
    Then the custom resource reports failure naming the reference
    And no router config item is written

  Scenario: The deploy needs no role change
    Given the monitoring stack template
    Then the config applier has its own role that can only get and put items
    And the hand seed script no longer exists
