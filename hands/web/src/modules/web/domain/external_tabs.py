"""Capacity requires a recognized inventory of the user's external tabs."""

import re


def require_tab_capacity(inventory: str, maximum: int) -> None:
    indexes = set(re.findall(r"(?m)^\s*-?\s*(\d+):", inventory))
    if not indexes and not re.search(r"no (?:open )?tabs", inventory, re.I):
        raise RuntimeError("EXTERNAL_TAB_INVENTORY_UNSUPPORTED")
    if len(indexes) >= maximum:
        raise RuntimeError("EXTERNAL_TAB_LIMIT_REACHED")
