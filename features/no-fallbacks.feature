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

  Scenario: The reader reads editions through the published-at index only
    Given the content repository source
    When it is read for how it finds the newest published editions
    Then it asks the published-at index directly and never checks whether the index exists or falls back to the edition-date index

  Scenario: A layout plan that names an unpublished item stops the build
    Given the content repository source
    When it is read for how it treats a layout block whose item did not load
    Then the plan is validated as written, no block is dropped with a warning, and no invented fallback image exists

  Scenario: The news desk lists References from their indexes only
    Given the news desk client source
    When it is read for how it loads a page of References
    Then each ordering and status filter reads its own index, an empty page is an empty page, and no table scan or older feed query takes over

  Scenario: Inbound email settings belong to the site and a missing one stops the build by name
    Given the inbound email settings
    When a site turns inbound email on without one of them
    Then the synth fails naming the missing setting, and no domain, corpus, hosted zone or site address of Papyrus's own is written into the engine
  Scenario: The steering workspace refreshes References without a subscription
    Given the steering workspace source
    When it is read for how the References page stays current
    Then it opens no realtime stream for References or relations, probes no subscription method, and shows no realtime status banner

  Scenario: A section is called by its own stored name and the page has one list of sections
    Given the steering workspace source
    When it is read for how it names a section and where its sections and proposals come from
    Then a section shows its stored short title or its title, no table of section names is written into the engine, and the page does not borrow a second snapshot when the first is empty

  Scenario: A dashboard query that fails fails the dashboard
    Given the news desk client source
    When it is read for how it loads the dashboard's lists
    Then every list is awaited as it is, a failed query rejects the load so the editor sees the error, and no empty list stands in for a failed one
