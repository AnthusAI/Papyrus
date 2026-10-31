Feature: Account-scoped operations are authorized by Prospectus, and fail closed
  A Papyrus login says who a person is; it does not say which account they may act in. Prospectus does, and it answers
  for one account at one moment. When a site turns authorization on, every account-scoped operation asks Prospectus just
  before it takes effect, as the site's own role, passing the person's own access token and the account they chose. Any
  doubt refuses: no account named, no answer, an answer for a different account. Pool groups alone are never enough.
  When Prospectus says the login is no longer enrolled, that is passed on unchanged so the CLI and the console can tell
  the person to sign in again. The backend's own functions are machines inside the site, not people, and are not asked.
  A site that has not switched this on is not affected at all.

  Background:
    Given a site that has switched on Prospectus authorization
    And a signed-in person who chose the account "acct-0001"

  Scenario: An allowed decision for the requested account lets the operation proceed
    When Prospectus allows "acct-0001" to write
    Then the operation proceeds
    And Prospectus was asked once, for "console:write" on "acct-0001", with the person's own token

  Scenario: A decision for a different account is treated as denied
    When Prospectus answers allowed, but for the account "acct-0002"
    Then the operation is refused as not authorized

  Scenario: reenrollment_required reaches the CLI as "run papyrus login again"
    When Prospectus says this login is no longer enrolled
    Then the operation is refused as needing re-enrollment
    And the CLI tells the person to run `papyrus login` again and exits with a failure

  Scenario: Prospectus unreachable denies the operation (fail closed)
    When Prospectus cannot be reached
    Then the operation is refused as not authorized

  Scenario: A request without X-Prospectus-Account is refused as account_required
    When the person sends a request that names no account
    Then the operation is refused as needing an account
    And the CLI tells the person to choose an account and exits with a failure

  Scenario: The site's own IAM functions are not subject to the human authorize check
    When the site's own function calls the operation with its role
    Then the operation proceeds without asking Prospectus

  Scenario: With the flag off the backend synthesizes exactly what it did before
    When the backend is synthesized with Prospectus authorization off and then on
    Then the backend with it off has no Prospectus data source, pipeline function, environment or permission
    And the backend with it on has all four
