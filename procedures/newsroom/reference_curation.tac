-- papyrus-procedure-kind: references.curate
-- Curation before review: capture, summarize and (for research papers) GROBID-extract one Reference.
--
-- The monitoring router starts this through the procedure runner right after it delivers a new pending
-- Reference (a publication's `procedureTriggers`), so an editor sees the Reference with its captured text,
-- completeness signals, summary and paper fields. It makes no editorial decision and never changes the
-- Reference's curation status. Running it again for a finished Reference does nothing.
--
-- Register it once per site:
--   papyrus procedures register --file procedures/newsroom/reference_curation.tac --key papyrus.reference.curate
-- and give the publication a trigger:
--   {"procedureKey": "papyrus.reference.curate", "input": {"reference_id": "{referenceId}"}}
-- Specs: features_backend/reference-curation-before-review.feature

-- The toolset is named after its tool because `Tool.get(name)` looks a toolset up by the name it is called with,
-- and this procedure has no agent: the tool runs deterministically, with no model deciding anything.
Toolset "papyrus_curate_reference" {
    type = "plugin",
    modules = {"papyrus_newsroom.tactus_tools"}
}

Procedure {
    input = {
        reference_id = field.string{required = true, description = "The Reference to curate (Reference.id)"},
        force = field.boolean{default = false, description = "Redo stages that already finished"}
    },
    output = {
        result = field.object{required = true}
    },
    function(input)
        local curate = Tool.get("papyrus_curate_reference")
        local result = curate({reference_id = input.reference_id, force = input.force == true})
        return {result = result}
    end
}
