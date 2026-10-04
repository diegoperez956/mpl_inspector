"""Tiny deterministic TOON-style encoder for agent-facing CLI output.

* scalars: ``key: value``
* dicts: ``key:`` followed by indented fields
* lists of flat dicts: ``key[N]{a,b}:`` followed by one comma-separated row each
* lists of scalars: ``key[N]: a,b`` (one per line when long)

Strings are quoted (JSON style) only when they would otherwise be ambiguous.
"""

from __future__ import annotations

import json
import re
from typing import Any

_PLAIN = re.compile(r"^[^\s,:\"\[\]{}#][^,\n\"]*(?<=\S)$|^[^\s,:\"\[\]{}#]$")
_RESERVED = {"true", "false", "null", "none", "-"}


def dumps(data: dict[str, Any]) -> str:
    return "\n".join(_lines(data, 0))


def _lines(data: dict[str, Any], depth: int) -> list[str]:
    pad = "  " * depth
    out: list[str] = []
    for key, value in data.items():
        if isinstance(value, dict):
            out.append(f"{pad}{key}:" if value else f"{pad}{key}: {{}}")
            out.extend(_lines(value, depth + 1))
        elif isinstance(value, list):
            out.extend(_list(key, value, depth))
        else:
            out.append(f"{pad}{key}: {scalar(value)}")
    return out


def _list(key: str, items: list[Any], depth: int) -> list[str]:
    pad, inner = "  " * depth, "  " * (depth + 1)
    if not items:
        return [f"{pad}{key}[0]:"]
    if all(isinstance(item, dict) for item in items):
        columns = list(items[0])
        if all(list(item) == columns for item in items):
            rows = [inner + ",".join(scalar(item[c]) for c in columns) for item in items]
            return [f"{pad}{key}[{len(items)}]{{{','.join(columns)}}}:", *rows]
        return [f"{pad}{key}[{len(items)}]:", *(inner + json.dumps(item, separators=(",", ":")) for item in items)]
    values = [scalar(item) for item in items]
    joined = ",".join(values)
    if len(joined) <= 80 and not any(" " in v for v in values):
        return [f"{pad}{key}[{len(items)}]: {joined}"]
    return [f"{pad}{key}[{len(items)}]:", *(inner + v for v in values)]


def scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, separators=(",", ":"))
    text = str(value)
    if not _PLAIN.match(text) or text.lower() in _RESERVED or _looks_numeric(text):
        return json.dumps(text, ensure_ascii=False)
    return text


def _looks_numeric(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True
