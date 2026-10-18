-- Papyrus ingestion reference registration procedure.
--
-- This procedure receives one reference intake payload and returns a normalized
-- dry-run result envelope. Persistence and assignment lifecycle are handled by
-- the outer Papyrus workflow.

Procedure {
    input = {
        externalItemId = field.string{required = true, description = "Stable external identifier for the reference source"},
        sourceUri = field.string{required = true, description = "Canonical source URI"},
        title = field.string{default = "", description = "Optional source title"},
        corpusKey = field.string{required = true, description = "Papyrus steering corpus key"}
    },
    output = {
        result = field.object{required = true}
    },
    function(input)
        local title = input.title or ""
        if title == "" then
            title = "Untitled source"
        end
        return {
            result = {
                ok = true,
                kind = "ingestion.reference.register",
                external_item_id = input.externalItemId,
                source_uri = input.sourceUri,
                title = title,
                corpus_key = input.corpusKey,
                status = "accepted"
            }
        }
    end
}
