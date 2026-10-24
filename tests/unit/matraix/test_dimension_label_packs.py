"""Dimension label packs: per-dimension sources and schema alignment."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
LABELS_DIR = REPO_ROOT / "persona" / "schema" / "labels"
SCHEMA_PATH = REPO_ROOT / "persona" / "schema" / "dimensions.json"

_spec = importlib.util.spec_from_file_location(
    "build_labels", LABELS_DIR / "build_labels.py"
)
build_labels = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_labels)


def _write_sources(
    sources_dir: Path,
    *,
    dimensions: dict | None = None,
    taxonomy: dict | None = None,
    review_status: str = "machine-assisted",
) -> None:
    sources_dir.mkdir(parents=True)
    (sources_dir / "meta.json").write_text(
        json.dumps({"reviewStatus": review_status}), encoding="utf-8"
    )
    if dimensions is not None:
        (sources_dir / "dimensions.json").write_text(
            json.dumps(dimensions, ensure_ascii=False), encoding="utf-8"
        )
    if taxonomy is not None:
        (sources_dir / "taxonomy.json").write_text(
            json.dumps(taxonomy, ensure_ascii=False), encoding="utf-8"
        )


def test_expand_keeps_translations_on_their_own_dimension(tmp_path: Path) -> None:
    _write_sources(
        tmp_path / "sources" / "xx",
        dimensions={
            "primary_language": {
                "label": "主要语言",
                "values": {
                    "Mandarin": "普通话",
                    "English": "English",
                    "Swahili": "斯瓦希里语",
                },
            }
        },
    )
    pack_path, text = build_labels.build_locale(
        "xx", labels_dir=tmp_path, schema_path=SCHEMA_PATH
    )
    assert pack_path == tmp_path / "dimensions.labels.xx.json"
    pack = json.loads(text)

    entry = pack["dimensions"]["primary_language"]
    assert entry["label"] == "主要语言"
    assert entry["values"]["Mandarin"] == "普通话"
    assert entry["values"]["Swahili"] == "斯瓦希里语"
    assert "English" not in entry["values"]
    assert "Hindi" not in entry["values"]
    # A shared English token on another dimension is not filled in.
    assert "english_proficiency" not in pack["dimensions"]

    assert pack["locale"] == "xx"
    assert pack["reviewStatus"] == "machine-assisted"
    assert pack["sourceHash"] == build_labels.file_sha256(SCHEMA_PATH)


def test_same_english_value_can_differ_per_dimension(tmp_path: Path) -> None:
    catalog, _ = build_labels.load_dimensions(SCHEMA_PATH)
    none_dims = [dim_id for dim_id, values in catalog.items() if "None" in values]
    assert len(none_dims) >= 2
    first, second = none_dims[0], none_dims[1]
    _write_sources(
        tmp_path / "sources" / "xx",
        dimensions={
            first: {"values": {"None": "不会"}},
            second: {"values": {"None": "无"}},
        },
    )
    _, text = build_labels.build_locale(
        "xx", labels_dir=tmp_path, schema_path=SCHEMA_PATH
    )
    pack = json.loads(text)
    assert pack["dimensions"][first]["values"]["None"] == "不会"
    assert pack["dimensions"][second]["values"]["None"] == "无"


def test_sources_reject_unknown_ids_and_values(tmp_path: Path) -> None:
    _write_sources(
        tmp_path / "sources" / "xx",
        dimensions={
            "not_a_dimension": {"label": "x"},
            "primary_language": {"values": {"Klingon": "x"}},
        },
    )
    with pytest.raises(ValueError) as excinfo:
        build_labels.build_locale("xx", labels_dir=tmp_path, schema_path=SCHEMA_PATH)
    message = str(excinfo.value)
    assert "unknown dimension id 'not_a_dimension'" in message
    assert "has no value 'Klingon'" in message


def test_expansion_is_deterministic(tmp_path: Path) -> None:
    _write_sources(
        tmp_path / "sources" / "xx",
        dimensions={"age_bracket": {"label": "年龄段", "values": {"18-24": "18–24 岁"}}},
    )
    _, first = build_labels.build_locale(
        "xx", labels_dir=tmp_path, schema_path=SCHEMA_PATH
    )
    _, second = build_labels.build_locale(
        "xx", labels_dir=tmp_path, schema_path=SCHEMA_PATH
    )
    assert first == second


def test_taxonomy_labels_are_packed(tmp_path: Path) -> None:
    _write_sources(
        tmp_path / "sources" / "xx",
        dimensions={"age_bracket": {"label": "年龄段"}},
        taxonomy={"background": "背景", "demographics": "人口统计"},
    )
    _, text = build_labels.build_locale(
        "xx", labels_dir=tmp_path, schema_path=SCHEMA_PATH
    )
    pack = json.loads(text)
    assert pack["taxonomy"]["background"] == "背景"
    assert pack["taxonomy"]["demographics"] == "人口统计"
    assert "career" not in pack["taxonomy"]


def test_taxonomy_rejects_unknown_ids(tmp_path: Path) -> None:
    _write_sources(
        tmp_path / "sources" / "xx",
        taxonomy={"not_a_node": "x"},
    )
    with pytest.raises(ValueError) as excinfo:
        build_labels.build_locale("xx", labels_dir=tmp_path, schema_path=SCHEMA_PATH)
    assert "unknown node id 'not_a_node'" in str(excinfo.value)


def test_committed_packs_are_valid_and_fresh() -> None:
    """Every committed pack matches the schema and its own sources exactly."""
    dimensions, _ = build_labels.load_dimensions(SCHEMA_PATH)
    source_hash = build_labels.file_sha256(SCHEMA_PATH)
    for pack_path in sorted(LABELS_DIR.glob("dimensions.labels.*.json")):
        pack = json.loads(pack_path.read_text(encoding="utf-8"))
        errors = build_labels.validate_pack(dimensions, pack, source_hash=source_hash)
        assert not errors, f"{pack_path.name}: {errors}"

        locale = pack["locale"]
        regenerated_path, regenerated = build_labels.build_locale(
            locale, labels_dir=LABELS_DIR, schema_path=SCHEMA_PATH
        )
        assert regenerated_path == pack_path
        assert regenerated == pack_path.read_text(encoding="utf-8"), (
            f"{pack_path.name} is stale — rerun "
            f"python persona/schema/labels/build_labels.py --locale {locale}"
        )
