/**
 * Files the projector writes into the site bucket when the plugin is on (the manifest's `staticAssets`). The privacy pages task
 * adds its paths here; the Python projector (`papyrus_content.projection.plugins`) must know the same names.
 */
export const ALEXA_STATIC_ASSETS: readonly string[] = [];
