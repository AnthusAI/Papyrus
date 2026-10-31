/**
 * Files the projector copies into the site bucket when the plugin is on (the manifest's `staticAssets`). None today: the privacy and
 * terms pages (`/alexa/privacy/`, `/alexa/terms/`) are pages the projector renders with the site's chrome, like the newsletter pages
 * (`standard/alexa_pages.py`), not copied files. The Python list (`PLUGIN_STATIC_ASSETS["alexa"]` in
 * `papyrus_content.projection.plugins`) must hold the same keys.
 */
export const ALEXA_STATIC_ASSETS: readonly string[] = [];
