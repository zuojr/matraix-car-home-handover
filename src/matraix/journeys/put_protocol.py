"""Exact finite user acts; malformed model JSON never grants facts or consent."""

import json

ACTS = {"continue", "clarify", "stop"}
STYLES = {"terse", "balanced", "polite"}
SOL_PUT_FORMAT = {
    "type": "json_schema",
    "name": "persona_act",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "act": {"type": "string", "enum": ["continue", "clarify", "stop"]},
            "style": {"type": "string", "enum": ["terse", "balanced", "polite"]},
        },
        "required": ["act", "style"],
        "additionalProperties": False,
    },
}


def parse_act(text):
    value = json.loads(text)
    if (
        not isinstance(value, dict)
        or set(value) - {"act", "style"}
        or not isinstance(value.get("act"), str)
        or value.get("act") not in ACTS
    ):
        raise ValueError("Select a legal user action: continue, clarify or stop")
    if (
        not isinstance(value.get("style", "balanced"), str)
        or value.get("style", "balanced") not in STYLES
    ):
        raise ValueError("Unknown rendering style")
    return value
