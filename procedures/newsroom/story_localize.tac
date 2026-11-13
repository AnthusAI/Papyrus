-- papyrus-procedure-kind: story.localize
-- The Story translation procedure (papyrus.story.localize, PPY-843a7c): one run translates one published Story into one language.
--
-- Stages (src/papyrus_content/localize/engine.py): collect, budget, translate (changed blocks only), normalize and parity, bilingual judge,
-- copy edit, refine, a convergence loop that ends when a round no longer reduces the findings, record provenance, gate. Every model edit is
-- checked against the English source again and a rewrite that makes faithfulness worse reverts. Each stage is stored, so a run that fails
-- (an outage, a timeout) continues from its finished stages next time; the same run key started again does nothing.
--
-- The model calls (translate, judge, refine) are made in the tool, by one GPT-6 Luna client: Humanus's bilingual judge is a Python callable,
-- and the three calls share the run's stored stages and its cost record (reported to the runner through model_usage).
--
-- The result is an unpublished version of the sibling lineage <story>--<language>, author AI, with no board stage. A held translation raises a
-- flag review request. It never publishes and never writes the English Story except the advice on stock phrasing it shares with the English.
--
-- Register (from the site repository, or this one):
--   papyrus procedures register --file procedures/newsroom/story_localize.tac --key <site>.story-localize --dry-run --json
-- Specs: features_backend/story-localize.feature and procedures/newsroom/tests/test_story_localize.py (this file through Tactus, models faked).

Toolset "papyrus_localize_story" {
    type = "plugin",
    modules = {"papyrus_newsroom.tactus_tools"}
}

Procedure {
    input = {
        story = field.string{required = true, description = "Primary Story lineage id"},
        language = field.string{required = true, description = "BCP 47 tag of the language to translate into (es-419, zh-Hans)"},
        ceilingUsd = field.number{default = 0, description = "A cap on this run's model spend; 0 leaves it to the learned prediction band"},
        sourceVersion = field.number{default = 0, description = "The source version this run is for; 0 is the published one"},
        runKey = field.string{default = ""},
        automationId = field.string{default = ""}
    },
    output = {
        story = field.string{required = true},
        language = field.string{required = true},
        version = field.string{required = true},
        hold = field.boolean{required = true},
        reason = field.string{required = true},
        outcome = field.string{required = true},
        published = field.boolean{required = true},
        rounds = field.number{required = true},
        revertedBlocks = field.number{required = true},
        costUsd = field.number{required = true},
        sourceCharacters = field.number{required = true}
    },
    function(input)
        local localize = Tool.get("papyrus_localize_story")
        local result = localize({story = input.story, language = input.language, ceiling_usd = input.ceilingUsd, source_version = input.sourceVersion})
        return {
            story = result.story,
            language = result.language,
            version = result.version,
            hold = result.hold,
            reason = result.reason,
            outcome = result.outcome,
            published = result.published,
            rounds = result.rounds,
            revertedBlocks = result.revertedBlocks,
            costUsd = result.costUsd,
            sourceCharacters = result.sourceCharacters
        }
    end
}
