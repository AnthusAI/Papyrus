"""The refusals a Broadcaster raises, by name, so the site's broadcast function can report one and the remote side raise the same kind (``remote_broadcaster``)."""
from __future__ import annotations

from typing import Any, Mapping

from .records import RecordError

SUBMIT_REFUSED, RECORD = "submit_refused", "record"


def error_code(error: Exception) -> str:
    from .caducus_x import SubmitRefused

    return SUBMIT_REFUSED if isinstance(error, SubmitRefused) else RECORD


def refusal(answer: Mapping[str, Any]) -> Exception:
    message = str(answer.get("message") or "The site's broadcast function refused the request.")
    if answer.get("error") == SUBMIT_REFUSED:
        from .caducus_x import SubmitRefused

        return SubmitRefused(message)
    return RecordError(message)
