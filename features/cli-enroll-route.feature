Feature: A site's enroll route makes a remote CLI login a Prospectus Person
  After `papyrus login --remote` exchanges its code, the CLI posts the challenge the approval page bound, its ID token
  and the broker transaction to the site's `/cli/enroll`, with its access token as the bearer. The route checks both
  tokens against the site's registered federation client and asks Prospectus to resolve them as the site. Enrollment
  is off for a site until it is switched on, and a site answers 404 and calls nothing until then. These scenarios use
  synthetic tokens and a stand-in for Prospectus; nothing is deployed and no real identity is involved.

  Scenario: The enroll route resolves a Person for the right tokens and state
    When the CLI posts a valid challenge, its tokens and the transaction to the enroll route
    Then the route answers with the Person's id and nothing else

  Scenario: A replay with other tokens is refused as challenge_replay; the same tokens return the same Person
    When the same challenge is posted again, first with the same tokens and then with other tokens
    Then the same tokens return the same Person
    And the other tokens are refused as challenge_replay

  Scenario: A login on the main web client cannot enroll and the CLI stores no session
    When a login made on the main web client posts to the enroll route
    Then the route refuses it as login_not_enrollable before asking Prospectus

  Scenario: Error responses name no service detail beyond the code
    When Prospectus refuses an enrollment in each documented way
    Then the route passes through only challenge_invalid, login_state, challenge_replay or reenrollment_required with their status
    And any other failure is answered as unavailable without the service's message

  Scenario: A login challenge is bound to a digest and validated before it is answered
    When the challenge route is asked for a remote login's digest or a local login's state
    Then Prospectus is asked for a challenge bound to exactly 64 lowercase hex characters, never an unbound one
    And a challenge without a uuid4 id, a well-formed nonce, an expiry within 300 seconds and a signed token is answered as unavailable

  Scenario: The challenge route is throttled per site and fails closed
    When more challenges are asked for than the site's bucket allows
    Then the route answers 429 and never reaches Prospectus
    And the bucket is one request per second with a burst of two unless the site sets its own, and a storage failure refuses the request

  Scenario: Enrollment is off unless a site switches it on
    When a site has not switched enrollment on
    Then the enroll route answers 404 and calls nothing
    And the site's pages function gets no challenge origin, throttle table or Prospectus access, so its stack is unchanged
