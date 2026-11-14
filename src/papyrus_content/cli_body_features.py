"""What the CLI validates a Story body against at save: the features of the site it writes to.

The page is rendered by the site's projector, in the site's content-actions function. The CLI cannot read that
function's settings, so on the signed-in lane it asks the site (``deriveMarkus`` answers with its features), and on an
operator's lane that projects locally it reads the same projector. The answer is read once per command, the first time a
body is validated. When the site cannot say (an older site, no network), the defaults apply: the page is then checked
once more by the site itself when it is saved or published.
"""

from __future__ import annotations

import json

from .markus_renderer.body_features import DEFAULT_FEATURES, BodyFeatures, install_body_features

QUERY = "query SiteBodyFeatures($input: AWSJSON!) { deriveMarkus(input: $input) }"
_known: BodyFeatures | None = None


def site_features_from_response(data: dict) -> BodyFeatures:
    response = data.get("deriveMarkus")
    response = json.loads(response) if isinstance(response, str) else (response or {})
    return BodyFeatures.from_dict(response.get("features"))


def _ask_site() -> BodyFeatures:
    from .projection.runtime import projection_configured, site_body_features
    from .user_auth_mode import user_auth_requested

    if projection_configured():
        return site_body_features()
    if not user_auth_requested():
        return DEFAULT_FEATURES
    from .graphql_authoring import create_authoring_client

    client, _claims = create_authoring_client()
    return site_features_from_response(client.graphql(QUERY, {"input": json.dumps({"frontMatterYaml": None, "bodyMarkus": ""})}))


def cli_body_features() -> BodyFeatures:
    global _known
    if _known is None:
        try:
            _known = _ask_site()
        except Exception:  # noqa: BLE001 - not knowing the site's settings never stops a save; the site checks it again
            _known = DEFAULT_FEATURES
    return _known


def install() -> None:
    global _known
    _known = None
    install_body_features(cli_body_features)


def uninstall() -> None:
    install_body_features(None)
