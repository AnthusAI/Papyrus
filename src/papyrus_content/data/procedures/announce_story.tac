-- papyrus-procedure-kind: announce_story
-- The announce agent's run for one wake (PPY-e3bb2b; definition src/papyrus_content/agent_definitions/core/announce.yaml).
--
-- A Story's page going live (its Item record entering the published stage) and a published Story's rating changing reach this agent from the Item change feed,
-- through the site's wake queue, and from nowhere else. The wake only says what happened: the run re-reads the Story as it is now and decides from that, so a
-- late, repeated or out-of-order wake changes nothing it should not. It makes one Announcement for the Story (the once-only key story-published:<Story>) and one
-- email Delivery for the every-item lists that carry it, at a rung that allows it. At observe it writes nothing but its run record. It never sends: a Delivery
-- goes only through its own approval and attempt.
--
-- It runs only on an agent's wake adopted as the responsibility "announce": `papyrus automations adopt --id announce --responsibility announce`.
-- Specs: features_backend/announce-durable-triggers.feature, features_backend/announce-agent-definition.feature

Toolset "papyrus_announce_story" {
    type = "plugin",
    modules = {"papyrus_newsroom.tactus_tools"}
}

Procedure {
    input = {
        story = field.string{required = true, description = "The Story's lineage id, from the wake"},
        version = field.string{required = true, description = "The version row the change was made on, from the wake"},
        change = field.string{required = true, description = "stage_entered (the page went live) or rated, from the wake"},
        what = field.string{default = "", description = "What changed, as the wake key names it"},
        stage = field.string{default = "", description = "The stage the Story entered, from the wake"}
    },
    output = {
        summary = field.string{required = true, description = "One sentence: what was decided for the Story and why"},
        result = field.object{required = true, description = "The Story, the lists that carry it, the Announcement and whether this run made it"},
        run_outcome = field.string{description = "acted, or nothing when the Story qualifies nowhere or is already announced; the runner records it"},
        run_outcome_reason = field.string{description = "announced, or why nothing was made"}
    },
    function(input)
        local announce = Tool.get("papyrus_announce_story")
        local result = announce({story = input.story, version = input.version, change = input.change, what = input.what, stage = input.stage})
        return {summary = result.summary, result = result, run_outcome = result.run_outcome, run_outcome_reason = result.run_outcome_reason}
    end
}
