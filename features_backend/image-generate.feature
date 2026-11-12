Feature: Pictures are generated from the publication's guidelines, only where a person has approved spending
  Generating a picture compiles the request from the publication's resolved image guidelines exactly as the prompt preview shows it, sends it to the one
  image provider the site has approved, and keeps the result as a private candidate in a round. Whether a site may generate, which models it prefers, whether
  spending is approved and the ceilings for a round and for a day all live in the generation setting of the publication's image guidelines. Only a person may
  change what spending is allowed; an agent trying gets human_required. A site starts with nothing configured and spend not approved, and then nothing is
  made and no provider is called. A person can ask for a set of four to choose from; unattended work makes one picture. A picture's cost is worked out from the
  tokens the provider reports, and a picture with no price on file is never shown as free. A candidate is unreviewed until a person looks. Applying puts a
  picture on a Story as a draft: a person applying makes it human-verified, an agent applying leaves it unreviewed and opens a review request, and nothing is
  ever published. A round may have no Story or Reference; its pictures are private and cannot be applied. Discarding deletes the private file and keeps the
  record. Nothing here calls a real image provider or writes production data: the specs use a fake provider and an in-memory store.

  Scenario: A site that has configured nothing generates nothing and calls no provider
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    And a fake image provider
    When a person generates a "cover" picture of type "cover-illustration" with no Story and no section with the brief "A locked filing cabinet"
    Then generation is refused with "generation_not_configured" because "no_models"
    And the provider was not called

  Scenario: A site with a model but spending not approved generates nothing
    Given an image publication "ours" whose guidelines allow the model "gpt-image-2.5-flare" but do not approve spending
    And a fake image provider
    When a person generates a "cover" picture of type "cover-illustration" with no Story and no section with the brief "A locked filing cabinet"
    Then generation is refused with "generation_not_configured" because "spend_not_approved"
    And the provider was not called

  Scenario: An approved site makes one private candidate from the exact compiled request
    Given an image publication "ours" whose guidelines approve spending on "gpt-image-2.5-flare"
    And a fake image provider
    When a person generates a "cover" picture of type "cover-illustration" with no Story and no section with the brief "A locked filing cabinet"
    Then the round has 1 candidate that is "ready" and "unreviewed"
    And the provider was asked for the same text the preview shows
    And the candidate file is kept under the private candidates folder
    And the candidate cost is worked out from the tokens the provider reported
    And the round is private

  Scenario: A person can ask for a set of four and an agent cannot
    Given an image publication "ours" whose guidelines approve spending on "gpt-image-2.5-flare"
    And a fake image provider
    When an agent generates a set of 4 "cover" pictures of type "cover-illustration" with no Story and no section with the brief "A locked filing cabinet"
    Then generation is refused with "set_needs_person"
    And the provider was not called
    When a person generates a set of 4 "cover" pictures of type "cover-illustration" with no Story and no section with the brief "A locked filing cabinet"
    Then the round has 4 candidates that are "ready" and "unreviewed"

  Scenario: A section can be named and a repeated request gives the first round again
    Given an image publication "ours" whose guidelines approve spending on "gpt-image-2.5-flare"
    And the section "security" has an image document that adds the guidance "Keep it quiet." and avoids "keys"
    And a fake image provider
    When a person generates as request "same" a "cover" picture of type "cover-illustration" for the section "security" with the brief "Section art"
    And a person generates as request "same" a "cover" picture of type "cover-illustration" for the section "security" with the brief "Section art"
    Then the provider was called once
    And the request the provider received holds "Keep it quiet."

  Scenario: One picture failing does not lose the others
    Given an image publication "ours" whose guidelines approve spending on "gpt-image-2.5-flare"
    And a fake image provider that is busy for the first picture
    When a person generates a set of 2 "cover" pictures of type "cover-illustration" with no Story and no section with the brief "A locked filing cabinet"
    Then candidate 1 failed with the retryable error "provider_busy"
    And candidate 2 is "ready"

  Scenario: The day's ceiling stops further spending
    Given an image publication "ours" whose guidelines approve spending on "gpt-image-2.5-flare" with a daily ceiling of 0.04 dollars
    And a fake image provider
    When a person generates a set of 4 "cover" pictures of type "cover-illustration" with no Story and no section with the brief "A locked filing cabinet"
    Then candidates 1 and 2 are "ready"
    And candidate 3 failed with the error "spend_ceiling_exceeded"
    And the provider was called 2 times

  Scenario: An agent cannot change what spending is approved, a person can
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    When an agent saves the guidelines approving spending on "gpt-image-2.5-flare"
    Then the guidelines save is refused with "human_required"
    When a person saves the guidelines approving spending on "gpt-image-2.5-flare"
    Then the guidelines save succeeds
    And asking what the site can generate says it is configured and approved

  Scenario: A section cannot set the site's generation settings
    Given an image publication "ours" with a saved style profile whose master prompt says "Flat shapes with generous rounded corners."
    When an admin tries to save a section image document for "security" that approves spending
    Then the section save is refused because generation cannot be set from a section

  Scenario: Discarding deletes the private file and keeps the record
    Given an image publication "ours" whose guidelines approve spending on "gpt-image-2.5-flare"
    And a fake image provider
    When a person generates a set of 2 "cover" pictures of type "cover-illustration" with no Story and no section with the brief "A locked filing cabinet"
    And a person discards candidate 1 because "Too busy"
    Then candidate 1 is "rejected" and its file is gone
    And discarding candidate 1 again is refused with "candidate_closed"
    When a person discards the whole round because "Kept the placeholder"
    Then the round is done and every candidate is "rejected"

  Scenario: A person applying a picture makes it human-verified and a draft
    Given an image publication "ours" whose guidelines approve spending on "gpt-image-2.5-flare"
    And a Story "story-1" in each publication
    And a fake image provider
    When a person generates a "cover" picture of type "cover-illustration" for the Story "story-1" with the brief "A locked filing cabinet"
    And a person applies candidate 1 to the Story "story-1" as the cover
    Then the apply succeeds as "human-verified"
    And the Story got a new version with the cover set and nothing was published
    And no review request was opened
    And candidate 1 is "applied"

  Scenario: An agent applying leaves the picture unreviewed and asks for a review
    Given an image publication "ours" whose guidelines approve spending on "gpt-image-2.5-flare"
    And a Story "story-1" in each publication
    And a fake image provider
    When an agent generates a "cover" picture of type "cover-illustration" for the Story "story-1" with the brief "A locked filing cabinet"
    And an agent applies candidate 1 to the Story "story-1" as the cover
    Then the apply succeeds as "unreviewed"
    And a review request was opened

  Scenario: Apply is refused for a Story that has moved on, a private round and a failed picture
    Given an image publication "ours" whose guidelines approve spending on "gpt-image-2.5-flare"
    And a Story "story-1" in each publication
    And a fake image provider
    When a person generates a "cover" picture of type "cover-illustration" for the Story "story-1" with the brief "A locked filing cabinet"
    And a person applies candidate 1 to the Story "story-1" with an out of date version
    Then the apply is refused with "stale_version"
    Given a fake image provider that is busy for the first picture
    When a person generates a "cover" picture of type "cover-illustration" with no Story and no section with the brief "Another"
    And a person applies candidate 2 to the Story "story-1" as the cover
    Then the apply is refused with "candidate_not_ready"

  Scenario: Reading a round says whether it is done
    Given an image publication "ours" whose guidelines approve spending on "gpt-image-2.5-flare"
    And a fake image provider
    When a person generates a set of 2 "cover" pictures of type "cover-illustration" with no Story and no section with the brief "A locked filing cabinet"
    And a person reads the round
    Then the round read says it is done with 2 candidates
    And reading a round that does not exist is refused with "not_found"

  Scenario: The default handlers cannot spend
    Then the default image handlers answer not implemented for generate, round, discard and apply

  Scenario: The OpenAI provider shapes its request and reports what the provider says, without reaching the network
    Given an OpenAI provider whose network is a fake that answers with a picture and 30000 output tokens
    When the provider is asked for a landscape picture with the quality "low"
    Then the fake network saw the model, the prompt, the size "1536x1024" and the quality "low"
    And the provider returned the picture and its token usage
    Given an OpenAI provider whose network is a fake that answers 429
    Then asking it fails with the retryable error "provider_busy"
    Given an OpenAI provider whose network is a fake that answers 400
    Then asking it fails with the non-retryable error "provider_failed"
