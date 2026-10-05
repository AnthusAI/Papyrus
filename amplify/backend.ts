import { defineSiteBackend } from "./site-backend";

// Papyrus's own backend (p.apyr.us production + sandboxes). Publication repos
// write the same one-liner with their own site config; see docs/standard-site.md.
export default defineSiteBackend({ backend: { productionAppId: "dbsyytcm9drqa" } });
