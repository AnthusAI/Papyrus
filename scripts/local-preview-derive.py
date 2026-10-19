"""Reads {"frontMatterYaml", "bodyMarkus"} as JSON on stdin and prints the same result the content-actions
deriveMarkus query returns, so the local preview renders real Markus (figures, directives, citations)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from papyrus_content.markus_renderer.derive import derive_body

request = json.load(sys.stdin)
derivation = derive_body(request.get("frontMatterYaml"), request.get("bodyMarkus") or "")
body_ir = derivation.body_ir
print(json.dumps({
    "ok": bool(derivation.ok),
    "bodyIrBytes": len(json.dumps(body_ir, separators=(",", ":")).encode("utf-8")) if body_ir else 0,
    "bodyIr": body_ir,
    "errors": [{"code": error.code, "message": error.message, "line": error.line} for error in derivation.errors],
}))
