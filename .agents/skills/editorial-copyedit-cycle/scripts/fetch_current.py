"""Read the current (latest) version of each article from a Papyrus newsroom. Read-only.

    <workdir>/pv/bin/python -I fetch_current.py <outdir> <slug> [<slug> ...]

Writes <outdir>/<slug>.md (bodyMarkus) and <outdir>/index.json (lineage, current id, version, stage).
Needs the environment printed by connect.sh.
"""
import json
import sys
from pathlib import Path

from papyrus_content.graphql_authoring import create_authoring_client
from papyrus_content.story_reporting import current_story_version, story_versions

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
client, _ = create_authoring_client()
index = {}
for slug in sys.argv[2:]:
    rows = client.list_by_index("itemBySlug", slug)
    lineages = sorted({row.get("lineageId") or row["id"] for row in rows})
    if len(lineages) != 1:
        print(f"skip {slug}: {len(lineages)} lineages"); continue
    current = current_story_version(client, lineages[0])
    (out / f"{slug}.md").write_text(current.get("bodyMarkus") or "", encoding="utf-8")
    index[slug] = {"lineage": lineages[0], "current": current["id"], "version": current.get("versionNumber"),
                   "versions": len(story_versions(client, lineages[0])), "stage": current.get("stage")}
    print(slug, index[slug])
(out / "index.json").write_text(json.dumps(index, indent=1))
