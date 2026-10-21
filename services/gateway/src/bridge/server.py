"""Briareus single-origin Gateway; Panel authentication belongs to Control Panel API."""

from __future__ import annotations

from ._node_assembly import configured_app

app = configured_app()

# Preserve the currently deployed ASGI_APP selector for a scoped cutover.
static_app = app
