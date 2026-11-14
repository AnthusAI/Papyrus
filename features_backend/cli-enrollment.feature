Feature: A remote CLI login is enrolled with Prospectus
  When a site switches enrollment on, approving `papyrus login --remote` obtains a Prospectus login challenge, through the site's own route, bound to
  the sign-in's transaction, and the CLI enrolls the finished login at the site before it keeps any session. The
  pages function holds no secret and no Prospectus access: it asks the site's own challenge route, which runs as the
  registered compute role, and binds nothing unless the answer is a usable, fresh, signed challenge. These scenarios run the real cli-login broker in memory with a stand-in for the site's challenge route.
  A local `papyrus login` enrolls the same way, binding the challenge to the CLI's own sign-in state.

  Scenario: Approving a remote login binds a challenge to the transaction digest and returns its nonce
    Given a site with enrollment switched on and a started remote login
    When the person approves it
    Then the site was asked for a challenge bound to the digest of the transaction, never the transaction itself
    And the Google sign-in uses the challenge's nonce
    And the waiting CLI receives the signed challenge as its enrollment

  Scenario: An unusable challenge binds nothing and the approval page says the service is unavailable
    Given a site with enrollment switched on and a started remote login
    When the person approves it but the site answers no usable challenge
    Then the approval page says the service is unavailable
    And the transaction is still unbound

  Scenario: A login on the main web client cannot enroll and the CLI stores no session
    Given a remote login whose enrollment the site refuses as login_not_enrollable
    When the CLI finishes the code exchange
    Then it stores no session and records no person
    And it says plainly that the site's sign-in client is not registered for enrollment

  Scenario: A re-bound login is told to run papyrus login again
    Given a remote login whose enrollment the site refuses as reenrollment_required
    When the CLI finishes the code exchange
    Then it stores no session
    And it says to run `papyrus login` again

  Scenario: An enrolled login records its Person next to the registry and no token
    Given a remote login the site enrolls as a Person
    When the CLI finishes the code exchange
    Then the Person's id is recorded for the site in the CLI's registry file
    And the registry file holds no token

  Scenario: A local login binds its own state and enrolls the same way
    Given a site that has switched enrollment on and a local login
    When the CLI signs in locally
    Then it asked the site for a challenge bound to its own state and used the challenge's nonce
    And it enrolled the finished login with that state and recorded the Person

  Scenario: A local login on a site that has not switched enrollment on is unchanged
    Given a site that has not switched enrollment on and a local login
    When the CLI signs in locally
    Then it passed no enrollment hooks and recorded no Person

  Scenario: Error responses name no service detail beyond the code
    Given a remote login whose enrollment fails with an internal error
    When the CLI finishes the code exchange
    Then the message names only the code and a short reason
