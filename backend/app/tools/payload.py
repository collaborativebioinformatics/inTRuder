"""Serialization shared by every tool.

Tool results go back to the model as text, so they are serialized in one place
and predictably: indented JSON, with anything unserializable stringified rather
than raising inside a tool call.
"""

from __future__ import annotations

import json
from typing import Any


def dump(payload: Any) -> str:
    return json.dumps(payload, indent=2, default=str)
