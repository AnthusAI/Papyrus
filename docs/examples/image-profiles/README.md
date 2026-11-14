# Draft starter image style profiles

Three DRAFT profiles for Ryan to correct before anything is saved: `machines-on-machines.json`, `threat-intelligence.json` and `shipped.json`. They are examples in this repository only. Nothing has been written to any backend.

Each file holds a `DRAFT` note, the `openQuestions` to answer first, the `exampleSlots` (the example pictures each image type should get, as names and notes, no files), `howToSave`, and the `profile` itself in the schemaVersion 2 shape (see [image style profiles](../../image-style-profiles.md)). Only the `profile` is saved: extract it with `jq .profile FILE`, run `papyrus images profile diff --file`, and save with `papyrus images profile save` after the questions are answered. A test (`src/papyrus_content/images/starter_profiles_test.py`) keeps every file valid under the profile validator.
