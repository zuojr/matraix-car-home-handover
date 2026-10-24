"""Build display-label packs for persona dimensions.

A label pack is a locale-specific overlay on ``persona/schema/dimensions.json``:
it translates dimension labels and enum values FOR DISPLAY ONLY. Canonical ids
and values stay English everywhere data is stored, filtered, stratified, or
scored. Missing translations fall back to the English strings at render time.

Sources are **per dimension** — one dimension never inherits another
dimension's value translations. ``None`` on a language field and ``None`` on a
skill field are independent rows.

Compact translation sources live under ``sources/<locale>/``:

- ``meta.json``         — ``{"reviewStatus": "machine-assisted" | "reviewed"}``
- ``dimensions.json``   — ``{"<dimension_id>": {"label": "...", "values":
  {"<English value>": "<translation>"}}}``. Omit any key to fall back to English.
- ``taxonomy.json``     — optional ``{"<group_or_subgroup_id>": "<label>"}`` for
  Layer-1 / Layer-2 filter accordion titles (Background, Demographics, …).

The generator copies these into ``dimensions.labels.<locale>.json`` in schema
order and validates against ``dimensions.json``. Regenerating from unchanged
sources is byte-identical, which CI enforces via ``--check``.

Usage:
    python persona/schema/labels/build_labels.py --locale ko
    python persona/schema/labels/build_labels.py --all --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

FORMAT_VERSION = "1.0"
GENERATOR = "persona/schema/labels/build_labels.py"
SOURCE_CATALOG = "persona/schema/dimensions.json"
PACK_NOTE = (
    "Display overlay only. Dimension ids and value keys stay English; "
    "never use translated strings for storage, filters, or scoring."
)
REVIEW_STATUSES = ("reviewed", "machine-assisted")

# Layer-1 / Layer-2 taxonomy node ids from
# ``application/playground/backend/service/persona_taxonomy.py`` (plus Other).
TAXONOMY_NODE_IDS: frozenset[str] = frozenset(
    {
        "background",
        "demographics",
        "language",
        "education",
        "career",
        "psychology",
        "personality",
        "worldview",
        "decision_making",
        "capability",
        "domains",
        "skills",
        "behavior",
        "personal_behavior",
        "interaction_state",
        "work_practices",
        "technology_use",
        "lifestyle",
        "interests",
        "culture",
        "health",
        "other",
        "uncategorized",
    }
)

LABELS_DIR = Path(__file__).resolve().parent
REPO_ROOT = LABELS_DIR.parents[2]
DEFAULT_SCHEMA_PATH = REPO_ROOT / SOURCE_CATALOG


def file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def load_dimensions(schema_path: Path) -> tuple[dict[str, list[str]], str | None]:
    """Return ``{dimension_id: [values...]}`` in schema order plus schemaVersion."""
    payload = json.loads(schema_path.read_text(encoding="utf-8"))
    dimensions: dict[str, list[str]] = {}
    for row in payload.get("dimensions") or []:
        if not isinstance(row, dict):
            continue
        dim_id = str(row.get("id") or "").strip()
        if not dim_id:
            continue
        values = [str(v) for v in (row.get("values") or []) if str(v).strip()]
        dimensions[dim_id] = values
    return dimensions, payload.get("schemaVersion")


def _read_optional_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def load_sources(sources_dir: Path) -> dict[str, Any]:
    meta = _read_optional_json(sources_dir / "meta.json")
    return {
        "reviewStatus": str(meta.get("reviewStatus") or "machine-assisted"),
        "dimensions": _read_optional_json(sources_dir / "dimensions.json"),
        "taxonomy": _read_optional_json(sources_dir / "taxonomy.json"),
    }


def validate_sources(
    dimensions: dict[str, list[str]], sources: dict[str, Any]
) -> list[str]:
    errors: list[str] = []

    if sources["reviewStatus"] not in REVIEW_STATUSES:
        errors.append(
            f"meta.json reviewStatus must be one of {REVIEW_STATUSES}, "
            f"got {sources['reviewStatus']!r}"
        )

    entries = sources["dimensions"]
    if entries and not isinstance(entries, dict):
        return errors + ["dimensions.json must contain an object keyed by dimension id"]

    for dim_id, entry in entries.items():
        if dim_id not in dimensions:
            errors.append(f"dimensions.json: unknown dimension id {dim_id!r}")
            continue
        if not isinstance(entry, dict):
            errors.append(f"dimensions.json: {dim_id!r} must map to an object")
            continue
        label = entry.get("label")
        if label is not None and (not isinstance(label, str) or not label.strip()):
            errors.append(f"dimensions.json: empty label for {dim_id!r}")
        values = entry.get("values")
        if values is None:
            continue
        if not isinstance(values, dict):
            errors.append(f"dimensions.json: {dim_id!r}.values must be an object")
            continue
        allowed = set(dimensions[dim_id])
        for value, translation in values.items():
            if value not in allowed:
                errors.append(f"dimensions.json: {dim_id!r} has no value {value!r}")
            if not isinstance(translation, str) or not translation.strip():
                errors.append(f"dimensions.json: empty translation for {dim_id}.{value}")

    taxonomy = sources.get("taxonomy") or {}
    if taxonomy and not isinstance(taxonomy, dict):
        errors.append("taxonomy.json must contain an object keyed by taxonomy node id")
    elif isinstance(taxonomy, dict):
        for node_id, translation in taxonomy.items():
            if node_id not in TAXONOMY_NODE_IDS:
                errors.append(f"taxonomy.json: unknown node id {node_id!r}")
                continue
            if not isinstance(translation, str) or not translation.strip():
                errors.append(f"taxonomy.json: empty label for {node_id!r}")

    return errors


def expand(
    dimensions: dict[str, list[str]],
    sources: dict[str, Any],
    *,
    locale: str,
    schema_version: str | None,
    source_hash: str,
) -> dict[str, Any]:
    """Copy per-dimension sources into a pack (schema order, deterministic).

    Translations never leak across dimension ids. A value string that appears
    on two dimensions must be translated on each dimension separately.
    """
    authored = sources["dimensions"]
    packed: dict[str, Any] = {}
    for dim_id, values in dimensions.items():
        raw = authored.get(dim_id)
        if not isinstance(raw, dict):
            continue
        entry: dict[str, Any] = {}
        label = raw.get("label")
        if isinstance(label, str) and label.strip() and label != dim_id:
            entry["label"] = label
        authored_values = raw.get("values") if isinstance(raw.get("values"), dict) else {}
        translated_values: dict[str, str] = {}
        for value in values:
            translation = authored_values.get(value)
            if (
                isinstance(translation, str)
                and translation.strip()
                and translation != value
            ):
                translated_values[value] = translation
        if translated_values:
            entry["values"] = translated_values
        if entry:
            packed[dim_id] = entry

    authored_taxonomy = sources.get("taxonomy") if isinstance(sources.get("taxonomy"), dict) else {}
    taxonomy: dict[str, str] = {}
    for node_id in sorted(TAXONOMY_NODE_IDS):
        translation = authored_taxonomy.get(node_id)
        if (
            isinstance(translation, str)
            and translation.strip()
            and translation != node_id
        ):
            taxonomy[node_id] = translation

    return {
        "formatVersion": FORMAT_VERSION,
        "locale": locale,
        "reviewStatus": sources["reviewStatus"],
        "generator": GENERATOR,
        "sourceCatalog": SOURCE_CATALOG,
        "sourceSchemaVersion": schema_version,
        "sourceHash": source_hash,
        "note": PACK_NOTE,
        "dimensions": packed,
        "taxonomy": taxonomy,
    }


def validate_pack(
    dimensions: dict[str, list[str]],
    pack: dict[str, Any],
    *,
    source_hash: str,
) -> list[str]:
    errors: list[str] = []
    if pack.get("formatVersion") != FORMAT_VERSION:
        errors.append(f"unsupported formatVersion {pack.get('formatVersion')!r}")
    if pack.get("reviewStatus") not in REVIEW_STATUSES:
        errors.append(f"invalid reviewStatus {pack.get('reviewStatus')!r}")
    if pack.get("sourceHash") != source_hash:
        errors.append(
            "sourceHash does not match the current dimensions.json — regenerate "
            "the pack against the updated schema"
        )
    packed = pack.get("dimensions")
    if not isinstance(packed, dict):
        return errors + ["pack is missing the dimensions object"]
    for dim_id, entry in packed.items():
        if dim_id not in dimensions:
            errors.append(f"pack: unknown dimension id {dim_id!r}")
            continue
        if not isinstance(entry, dict):
            errors.append(f"pack: {dim_id!r} must map to an object")
            continue
        allowed = set(dimensions[dim_id])
        for value in entry.get("values") or {}:
            if value not in allowed:
                errors.append(f"pack: {dim_id!r} has no value {value!r}")
    taxonomy = pack.get("taxonomy")
    if taxonomy is None:
        taxonomy = {}
    if not isinstance(taxonomy, dict):
        errors.append("pack taxonomy must be an object")
    else:
        for node_id, translation in taxonomy.items():
            if node_id not in TAXONOMY_NODE_IDS:
                errors.append(f"pack: unknown taxonomy node id {node_id!r}")
            if not isinstance(translation, str) or not translation.strip():
                errors.append(f"pack: empty taxonomy label for {node_id!r}")
    return errors


def serialize(pack: dict[str, Any]) -> str:
    return json.dumps(pack, ensure_ascii=False, indent=2) + "\n"


def build_locale(
    locale: str,
    *,
    labels_dir: Path = LABELS_DIR,
    schema_path: Path = DEFAULT_SCHEMA_PATH,
) -> tuple[Path, str]:
    """Return (pack path, serialized pack) for one locale, validating sources."""
    sources_dir = labels_dir / "sources" / locale
    if not sources_dir.is_dir():
        raise FileNotFoundError(f"no translation sources at {sources_dir}")
    dimensions, schema_version = load_dimensions(schema_path)
    sources = load_sources(sources_dir)
    errors = validate_sources(dimensions, sources)
    if errors:
        raise ValueError(
            f"invalid sources for {locale!r}:\n" + "\n".join(f"- {e}" for e in errors)
        )
    source_hash = file_sha256(schema_path)
    pack = expand(
        dimensions,
        sources,
        locale=locale,
        schema_version=schema_version,
        source_hash=source_hash,
    )
    return labels_dir / f"dimensions.labels.{locale}.json", serialize(pack)


def discover_locales(labels_dir: Path = LABELS_DIR) -> list[str]:
    sources_root = labels_dir / "sources"
    if not sources_root.is_dir():
        return []
    return sorted(p.name for p in sources_root.iterdir() if p.is_dir())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--locale", help="build one locale (e.g. ko, ja, pt-BR, es)")
    parser.add_argument(
        "--all", action="store_true", help="build every locale under sources/"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify committed packs are byte-identical to regenerated output",
    )
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA_PATH)
    parser.add_argument("--labels-dir", type=Path, default=LABELS_DIR)
    args = parser.parse_args(argv)

    locales = (
        discover_locales(args.labels_dir)
        if args.all
        else ([args.locale] if args.locale else [])
    )
    if not locales:
        parser.error("pass --locale <code> or --all")

    failures = 0
    for locale in locales:
        pack_path, text = build_locale(
            locale, labels_dir=args.labels_dir, schema_path=args.schema
        )
        if args.check:
            current = (
                pack_path.read_text(encoding="utf-8") if pack_path.is_file() else None
            )
            if current != text:
                print(f"STALE {pack_path} — rerun the generator", file=sys.stderr)
                failures += 1
            else:
                print(f"OK {pack_path}")
        else:
            pack_path.write_text(text, encoding="utf-8")
            print(f"WROTE {pack_path}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
