"""Component name normalisation.

Only rule-based cleanup lives here: trimming CAD noise such as trailing revision
suffixes and instance counters. Mapping a name to a technical concept ("bearing",
"軸受") is a model judgement and happens in the AI layer with source="ai".
"""

from __future__ import annotations

import re

NOISE = [
    re.compile(r"[-_ ]?(rev|ver|v)[-_ ]?\d+$", re.IGNORECASE),
    re.compile(r"[-_ ]?\(\d+\)$"),
    re.compile(r"[-_ ]?instance[-_ ]?\d+$", re.IGNORECASE),
    re.compile(r"[-_ ]?\d+$"),
]


def normalize_name(raw: str | None) -> str | None:
    if raw is None:
        return None
    name = raw.strip().replace("\u3000", " ")
    if not name:
        return None
    for pattern in NOISE:
        name = pattern.sub("", name)
    name = re.sub(r"[_]+", " ", name).strip()
    return name or None
