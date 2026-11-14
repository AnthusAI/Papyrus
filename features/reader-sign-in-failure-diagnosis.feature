@brand-agnostic
Feature: Reader sign-in failures can be diagnosed
  When a reader's Google sign-in through Prospectus fails, the operator can tell where it stopped
  and the reader can report why. The callback logs one structured line per failure, and the Sign in
  control shows the failure code in small print. These scenarios are verified by
  scripts/test-prospectus-sign-in-routes.ts (npm run test:prospectus-sign-in-routes) and
  scripts/test-reader-islands.ts, which run in CI.

  Scenario: A failed callback logs one line naming the code and the branch
    Given a reader whose sign-in callback fails because the sign-in tokens carry the wrong nonce
    When the callback runs
    Then exactly one line starting "prospectus_sign_in_failed" is logged
    And the line names the code "nonce_mismatch", the branch "completion", the HTTP status and the Prospectus error code

  Scenario: Every failure branch is logged
    Given callbacks that fail with no pending cookie, a declined sign-in, missing parameters, a forged state, a refused code exchange and an unexpected error
    When each callback runs
    Then each logs one line with its own code and branch

  Scenario: The log line never carries secrets
    Given a failed callback that was given an authorization code, access and identity tokens and a state
    When the failure is logged
    Then the line contains none of those values, no email and no person or site subject

  Scenario: The reader sees the failure code in small print
    Given a reader returns to the page with sign_in_error "state_mismatch"
    Then the Sign in control says "Sign-in did not complete. Try again." followed by "(code: state_mismatch)"
    And the code is removed from the address bar

  Scenario: A declined sign-in shows no code
    Given a reader returns to the page with sign_in_error "sign_in_declined"
    Then the Sign in control says "Sign-in was cancelled." with no code

  Scenario: An odd code is never shown
    Given a reader returns to the page with a sign_in_error that is not a plain lower-case code
    Then the Sign in control says "Sign-in did not complete. Try again." with no code

  Scenario: A Prospectus refusal is logged with its rule text
    Given Prospectus refuses to resolve the sign-in with a 401 "challenge_invalid" and the message "Challenge does not exist."
    When the callback runs
    Then the logged line carries the code, the branch, the HTTP status, the Prospectus error code and "prospectusMessage" with that rule text
    And the line still contains no token, code, state, email or subject
