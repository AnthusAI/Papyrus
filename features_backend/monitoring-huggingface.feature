Feature: A Hugging Face Hub Monitor collects new machine-learning models with the fields a knowledge map needs
  A monitor of the Hugging Face model list is configured as data: pipeline tags, a watchlist of
  organisations, search terms and minimum signals. It collects the public model list into the same
  discovery table as every other monitor, keeps each model's structured fields, and never reads
  model card text. The router delivers by the monitor's own rule until a Cyclotron has criteria.

  Scenario: Collect new models that reach the monitor's minimum signal
    Given a Hugging Face monitor for text-to-speech models that need at least 1 like
    And the Hub lists twelve new text-to-speech models and one of them has a like
    When the Hugging Face monitor collects
    Then one discovery is recorded, for the model that has the like
    And that discovery carries the model id, author, release date, pipeline tag, license, tags, library, likes, downloads and canonical URL
    And that discovery waits for the router and records that it came from Hugging Face

  Scenario: A watchlisted organisation is collected whatever its signals
    Given a Hugging Face monitor that watches the organisation nvidia for robotics models
    And the Hub lists three new nvidia models, two of them robotics
    When the Hugging Face monitor collects
    Then both robotics models are collected although neither has a like
    And the model with no pipeline tag is left out

  Scenario: Collect the same model again without duplicating it
    Given a Hugging Face monitor for text-to-speech models that need at least 1 like
    And the Hub lists twelve new text-to-speech models and one of them has a like
    And the Hugging Face monitor has collected
    When the Hugging Face monitor collects a day later and only that model's likes have changed
    Then the model is reported unchanged and has one discovery
    When the Hugging Face monitor collects another day later and the model has a new commit
    Then the model has a second discovery revision that carries the new commit

  Scenario: Backfill a window of history, bounded and repeatable
    Given a Hugging Face monitor for text-generation models that need at least 5000 likes
    And the Hub lists the most-liked text-generation models
    When the operator backfills models created since the middle of 2024
    Then the two models inside the window are loaded and the third is not
    When the operator backfills the same window again
    Then nothing is read or written twice

  Scenario: A backfill that hits its request bound resumes where it stopped
    Given a Hugging Face monitor for text-generation models that need at least 5000 likes
    And the Hub lists the most-liked text-generation models
    When the operator backfills with room for only one Hub request
    Then the backfill reports that it paused and stored a checkpoint
    When the operator backfills the same window again with room to finish
    Then the backfill continues from the stored cursor and completes with all models loaded once

  Scenario: The models a model was built on become relation-ready fields
    Given a Hugging Face monitor for text-to-speech models that need no minimum
    And the Hub lists twelve new text-to-speech models and one of them has a like
    When the Hugging Face monitor collects
    Then a quantized model lists its base model with the relation quantized
    And a fine-tuned model lists its base model with the relation finetune
    And a model that declares no base lists none

  Scenario: A monitor's own rule delivers qualifying models to a publication
    Given a Hugging Face monitor for text-to-speech models that need no minimum
    And the Hub lists twelve new text-to-speech models and one of them has a like
    And the Hugging Face monitor has collected
    And the router for Shipped delivers by the monitor's rule that a model needs at least 1 like
    When the router runs
    Then the liked model is delivered to Shipped as a pending Reference candidate
    And the other eleven models are finished without delivery and say that the rule excluded them
    And a second router run finds nothing waiting

  Scenario: Only addresses on huggingface.co are accepted
    Then a monitor source address on another host is refused
    And a next-page cursor that leaves huggingface.co is refused
