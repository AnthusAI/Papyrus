@brand-agnostic
Feature: One correct path that fails clearly
  Papyrus code has one path. It does not probe the backend schema to decide which fields or queries to use, it does not keep a
  second reduced query for an older backend, it does not retry under another credential, and it does not invent a value when the
  real one is missing. When the backend or the configuration is not what the code needs, the operation stops and says what is
  missing, so the fix is made where the cause is: deploy the schema, supply the setting. This feature collects the places that
  have been cleaned up, one scenario per area. The scenarios read the source and run the real helpers; they deploy nothing.

  Scenario: The console chat client asks the backend for exactly the fields it needs
    Given the console chat client source
    When it is read for schema probing and reduced-field queries
    Then it runs no introspection query, keeps no legacy field set, and names every field of the message and thread queries once

  Scenario: The console chat client uses the signed-in editor and no other credential
    Given the console chat client source
    When it is read for how it authorizes a request
    Then every request uses the signed-in editor's credential and there is no retry under the public key

  Scenario: The console chat client reports a failure instead of inventing a result
    Given the console chat client source
    When it is read for how it handles a failed thread or message operation
    Then a failed create, update or list raises the backend's error and no thread is made up from messages or from the input
