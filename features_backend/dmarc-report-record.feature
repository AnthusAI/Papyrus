Feature: Every sending domain publishes DMARC, and the aggregate reports go to a mailbox whose address is not in Git
  A DMARC record at a sending domain tells receiving mail systems what to do with mail that fails SPF and DKIM alignment, and where to send the aggregate (rua)
  reports about who is sending as the domain. Without one nobody sees who sends as us. The record is published from a template in Git and applied by the release
  pipeline; nobody makes a DNS record by hand. The mailbox that receives the reports is an existing mailbox on the anth.us domain, and its address is a deployment
  parameter: the stack holds only the NAME of an SSM parameter, CloudFormation reads the value at deploy time, and the address is never in the repository, a spec,
  a fixture, a document or the board (these specs use the placeholder dmarc-reports@example.test). The policy starts at none, which only reports. Moving to quarantine
  and then reject is its own reviewed change, made when the reports show SPF and DKIM aligned for every legitimate sender. Nothing here has been deployed: the
  parameter is created once by a person, and the release publishes the records once the pipeline roles allow the DMARC stacks (the stacks come in a follow-up change, after a person approves the roles).

  Scenario: The record is a DMARC TXT record at the sending domain with the report address in it
    Given the DMARC template
    When it is rendered for the domain "mail.example.test" with the report address "dmarc-reports@example.test"
    Then the record is a TXT record named "_dmarc.mail.example.test"
    And the record reads "v=DMARC1; p=none; adkim=r; aspf=r; rua=mailto:dmarc-reports@example.test"

  Scenario: The policy starts at none and a stricter one is a choice the template allows only by name
    Given the DMARC template
    Then the policy parameter defaults to "none"
    And the policy parameter allows only "none", "quarantine" and "reject"

  Scenario: The report address is the value of an SSM parameter, resolved at deploy time
    Given the DMARC template
    Then the report address parameter is an SSM parameter value, so CloudFormation reads it at deploy time
    And its default is a parameter name that starts with a slash, not an address

  Scenario: A mailbox on the same organisational domain needs no external-destination record
    Given the DMARC template
    Then the template says a mailbox on another domain needs an authorization record in that domain's zone
    And the template creates no authorization record

  Scenario: The release's roles may drive the DMARC stacks and nothing else new
    Given the release roles template
    Then the plan role may read the DMARC stacks
    And the deploy role may drive the DMARC stacks only through the service role
    And the deploy role may resolve the report address parameter under /papyrus/

  Scenario: No real address is in the repository's DMARC files
    Given the DMARC template and its specs
    Then none contains an email address other than the example.test placeholder
