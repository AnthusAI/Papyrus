Feature: Every CloudWatch alarm in papyrus-production reaches Ryan as one triage-ready email
  Until now an alarm meant an SNS email with the alarm's name and a threshold, only five of 47 alarms had any action at all, and the
  Amplify site alarms notified nobody. The operator listener in the papyrus-monitoring stack listens to every alarm state change on the
  account's default bus, turns an alarm and its clearing into one message each, groups alarms that fire together, and sends it from
  notify.anth.us with what broke, where, the impact, the next step and a link. The existing SNS email keeps working beside it. Two
  alerts stay on SNS because they must work when the listener does not: SES in trouble, and a dead-man's switch that watches a
  heartbeat travelling the real path. Nothing here is deployed by a test; the template is read as data.

  Scenario: Every alarm state change in the account goes to the listener, and the listener's own alarms do not echo
    Given the operator listener template
    Then a rule on the default bus takes every CloudWatch alarm state change
    And that rule skips alarms named "papyrus-operator-" and sends the rest to the ingest queue
    And the reconcile function skips the same prefix

  Scenario: Failures end up in dead-letter queues, not in the void
    Given the operator listener template
    Then the ingest queue and the email queue each redrive to their own dead-letter queue
    And both dead-letter queues keep messages for fourteen days

  Scenario: Mail is sent only from the operator identity, and no address is in the repository
    Given the operator listener template
    Then the email function may send only as the alerts mailbox of the operator domain, with the operator configuration set
    And the operator listener template contains no email address
    And the operators are read from the SSM parameter that the alarm topic's subscription already uses

  Scenario: Each role has only what its job needs
    Given the operator listener template
    Then only three grants name no resource, and each is one that AWS cannot scope
    And the listener's roles read exactly three parameters and decrypt with no key grant

  Scenario: The existing alarm email keeps working during the parallel run
    Given the operator listener template
    Then the five existing monitoring alarms still notify the alarm topic
    And the topic still has its email subscription
    And no existing resource of the stack is changed by the operator listener

  Scenario: The two last-resort alerts are the only operator alarms on SNS
    Given the operator listener template
    Then exactly two alarms named "papyrus-operator-" notify the alarm topic, on ALARM and on OK
    And the dead-man alarm breaches when fewer than one heartbeat is delivered in each of three fifteen minute periods
    And the SES alert is one composite alarm over the bounce rate, the complaint rate and a refused heartbeat send

  Scenario: The heartbeat runs the real path
    Given the operator listener template
    Then a schedule puts a heartbeat event on the ingest queue every fifteen minutes with a different event id each time
    And a rule sends SES events of the operator configuration set to a function that counts the delivered heartbeat

  Scenario: A real alarm arrives with notes Papyrus wrote for it
    Given Papyrus's alarm catalog and the caducus package
    When the alarm "papyrus-monitoring-router-dead-letters" fires
    Then one email is sent with what broke, the impact, the next step and a link
    And the next step says to redrive the dead-letter queue

  Scenario: An alarm nobody wrote notes for still sends, and says so
    Given Papyrus's alarm catalog and the caducus package
    When the alarm "some-new-team-alarm" fires
    Then one email is sent that says "No triage notes yet"

  Scenario: Amplify site alarms explain themselves from what they measure
    Given Papyrus's alarm catalog and the caducus package
    Then the deploy render drift alarm tells the operator to reconcile with a dry run first and that nothing was deleted
    And the invalidation paths alarm says it is about the free monthly allowance and that readers are not affected
    And no app id, account id or address is in the catalog

  Scenario: The test alarm proves the path without touching anything else
    Given Papyrus's alarm catalog and the caducus package
    When the test alarm is set to ALARM and then to OK
    Then exactly two emails are sent, one for the alarm and one for clearing it
    And the test alarm has no alarm actions, so neither the SNS email nor any other system hears it

  Scenario: The operator sending identity uses the newsletter's template and never tracks
    Given the newsletter sending stack template
    Then it sends delivery events to the default event bus when asked, and keeps the SNS topic by default
    And no event destination of the stack includes opens or clicks

  Scenario: The listener's code is one pinned package and the catalog, in a deterministic zip with no PyYAML
    Given the operator zip build
    Then the pin is a single line that is easy to change to a PyPI version
    And building twice from the same pin and catalog gives the same bytes
    And the zip holds no PyYAML and is far inside Lambda's size limits
