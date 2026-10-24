"""Small, deterministic file helpers; no provider credentials in artifacts."""

from __future__ import annotations
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIN = "54990894241f2c07e9b523928c2a29e9b693d313"
COHORTS = {
    "C1": {"priority": "time", "disclosure": "proactive"},
    "C2": {"priority": "time", "disclosure": "on_demand"},
    "C3": {"priority": "tolls", "disclosure": "proactive"},
    "C4": {"priority": "tolls", "disclosure": "on_demand"},
}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def clock(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def tool(name, description, properties=None, required=None):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties or {},
                "required": required or [],
                "additionalProperties": False,
            },
        },
    }
