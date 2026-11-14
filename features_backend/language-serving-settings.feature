Feature: How a site serves its languages, and the slug each translation is first published under
  The site's one languages setting says which languages it writes in. Three more keys say how they are served: the URL prefix of each
  language, which languages are public, and how each language's slugs are drafted. A translation's slug is drafted in its own language at
  its first publish and then fixed, like every slug. Chinese readers get addresses in Chinese characters.

  Scenario: Each language gets its base subtag as its prefix unless the site names one
    Given the languages setting enables "en, es-419, zh-Hans" with "en" as the primary
    When the serving languages are read
    Then "es-419" is served under "es" and "zh-Hans" under "zh", and "en" at the root

  Scenario: Only the primary is public until the site says otherwise
    Given the languages setting enables "en, es-419" with "en" as the primary
    When the serving languages are read
    Then the public languages are "en"

  Scenario: A prefix two languages share is refused
    Given the languages setting enables "en, es-419, es" with "en" as the primary
    When the serving languages are read
    Then the setting is refused naming "would both be served under /es/"

  Scenario: A public list without the primary is refused
    Given the languages setting enables "en, es-419" with "en" as the primary
    And the public languages are set to "es-419"
    When the serving languages are read
    Then the setting is refused naming "must include the primary language en"

  Scenario: Slug policies default by script: translated for Spanish, characters for Chinese
    Given the languages setting enables "en, es-419, zh-Hans" with "en" as the primary
    When the serving languages are read
    Then the slug policy of "es-419" is "translated" and of "zh-Hans" is "characters"

  Scenario: A Spanish title becomes a translated slug in plain letters
    When a slug is drafted from "El sonido que puede delatar dónde vives" with the policy "translated"
    Then the slug is "el-sonido-que-puede-delatar-donde-vives"

  Scenario: A Chinese title keeps its characters, without punctuation
    When a slug is drafted from "AI，会说谎吗？「真相」" with the policy "characters"
    Then the slug is "ai-会说谎吗-真相"

  Scenario: Full-width letters and digits become ordinary ones, and an ideographic space a hyphen
    When a slug is drafted from "ＧＰＴ６　发布" with the policy "characters"
    Then the slug is "gpt6-发布"

  Scenario: Only a title longer than a directory name can hold is cut, at a whole character
    When a slug is drafted from a Chinese title of 100 characters with the policy "characters"
    Then the slug is its first 85 characters, 255 bytes of UTF-8, the most a directory name holds
    And the longest Chinese page address stays within an S3 key and a CloudFront request line once percent-encoded

  Scenario: A Chinese title of ordinary length is kept whole
    When a slug is drafted from a Chinese title of 40 characters with the policy "characters"
    Then the slug is the whole title

  Scenario: A title that leaves nothing gets no invented address
    When a slug is drafted from "？！……" with the policy "characters"
    Then the drafting is refused and asks for a slug to be given

  Scenario: The primary policy keeps the original's slug, and pinyin needs a romanizer
    When a slug is drafted from "能泄露你住在哪里的声音" with the policy "primary" and the original slug "the-sound"
    Then the slug is "the-sound"
    When a slug is drafted from "能泄露你住在哪里的声音" with the policy "pinyin" and the romanizer "neng xie lou ni zhu zai na li de sheng yin"
    Then the slug is "neng-xie-lou-ni-zhu-zai-na-li-de-sheng-yin"

  Scenario: A slug another Story of the same language has gets a number
    Given the Chinese Stories already use "你住在哪里" and "你住在哪里-2"
    When the slug "你住在哪里" is made unique within Chinese
    Then the slug is "你住在哪里-3"
