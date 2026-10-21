"""A public form defined as data: accessible markup and a small submit script.

``render_form`` returns the form for one :class:`FormSpec`. With an endpoint the script (``_plugins/papyrus-form-v1.js``)
posts the fields as JSON to the endpoint plus ``?form=<id>``, with ``page`` (the page path) and the honeypot field, and shows the success text only for a
2xx answer; any other outcome shows the failure text. Without an endpoint the form is a disabled fieldset under a
"not open yet" notice and has nothing to submit: it never fakes success. The receiving endpoint is not part of the
front end.
"""

from __future__ import annotations

import html
from urllib.parse import parse_qsl, quote

from .config import FormField, FormSpec

FORM_SCRIPT_PATH = "_plugins/papyrus-form-v1.js"


def _q(value) -> str:
    return html.escape(str(value), quote=True)


def _submit_url(endpoint: str, form_id: str) -> str:
    """The endpoint with the form id as ``?form=``: the shared receiving endpoint tells forms apart by it."""
    base, hash_mark, fragment = endpoint.partition("#")
    path, _, query = base.partition("?")
    if "form" in dict(parse_qsl(query)):
        return endpoint
    query = f"{query}&" if query else ""
    return f"{path}?{query}form={quote(form_id, safe='')}{hash_mark}{fragment}"


def _field(form_id: str, field: FormField) -> str:
    field_id = f"{form_id}-{field.name}"
    required = " required" if field.required else ""
    autocomplete = f' autocomplete="{_q(field.autocomplete)}"' if field.autocomplete else ""
    described = f' aria-describedby="{field_id}-help"' if field.help else ""
    if field.type == "textarea":
        control = f'<textarea id="{field_id}" name="{_q(field.name)}" rows="6"{required}{autocomplete}{described}></textarea>'
    elif field.type == "select":
        options = "".join(f'<option value="{_q(value)}">{_q(label)}</option>' for value, label in field.options)
        control = f'<select id="{field_id}" name="{_q(field.name)}"{required}{described}>{options}</select>'
    else:
        control = f'<input id="{field_id}" name="{_q(field.name)}" type="{field.type}"{required}{autocomplete}{described}>'
    marker = ' <span class="markus-form-required" aria-hidden="true">*</span>' if field.required else ""
    help_text = f'<p class="markus-form-help" id="{field_id}-help">{_q(field.help)}</p>' if field.help else ""
    return f'<div class="markus-form-field"><label for="{field_id}">{_q(field.label)}{marker}</label>{control}{help_text}</div>'


def render_form(spec: FormSpec) -> str:
    form_id = f"form-{spec.id}"
    fields = "".join(_field(form_id, field) for field in spec.fields)
    honeypot = (
        f'<div class="markus-form-trap" aria-hidden="true"><label>Leave this empty'
        f'<input type="text" name="{_q(spec.honeypot)}" tabindex="-1" autocomplete="off"></label></div>'
    )
    heading = f'<h2 id="{form_id}-title">{_q(spec.title)}</h2>' if spec.title else ""
    if spec.endpoint is None:
        return (
            f'<section class="markus-form markus-form-closed" aria-labelledby="{form_id}-title">{heading}'
            f'<p class="markus-form-notice" role="status">{_q(spec.closed_notice)}</p>'
            f'<form><fieldset disabled>{fields}<button type="button" disabled>{_q(spec.submit_label)}</button></fieldset></form></section>'
        )
    submit_url = _submit_url(spec.endpoint, spec.id)
    return (
        f'<section class="markus-form" aria-labelledby="{form_id}-title">{heading}'
        f'<form id="{form_id}" method="post" action="{_q(submit_url)}" data-papyrus-form="{_q(spec.id)}" '
        f'data-endpoint="{_q(submit_url)}" data-success="{_q(spec.success_text)}" data-failure="{_q(spec.failure_text)}">'
        f'{fields}{honeypot}<button type="submit">{_q(spec.submit_label)}</button>'
        f'<p class="markus-form-status" role="status" aria-live="polite" hidden></p></form></section>'
    )
