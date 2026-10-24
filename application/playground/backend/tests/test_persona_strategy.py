"""Tests for per-task persona_strategy.json loading and validation."""

from __future__ import annotations

import json

from backend.service.persona_strategy import (
    load_persona_strategy,
    normalize_persona_strategy,
    validate_persona_strategy_file,
)
from backend.service.task_detail_service import get_task_detail


def test_normalize_new_sampling_block() -> None:
    payload = normalize_persona_strategy(
        {
            "schemaVersion": "1.0",
            "dimensionFilters": {"age_bracket": ["25-34"]},
            "sampling": {
                "mode": "stratified",
                "fields": ["age_bracket"],
                "allocation": "proportional",
                "sampleSize": 20,
            },
        }
    )
    assert payload["sampling"]["mode"] == "stratified"
    assert payload["sampling"]["allocation"] == "proportional"
    assert payload["sampling"]["sampleSize"] == 20
    assert payload["dimensionFilters"] == {"age_bracket": ["25-34"]}
    assert "defaultMode" not in payload
    assert "sampleSize" not in payload


def test_normalize_preserves_portions_for_proportional() -> None:
    payload = normalize_persona_strategy(
        {
            "schemaVersion": "1.0",
            "dimensionFilters": {"economic_motivation": ["Cost-sensitive", "Premium-seeking"]},
            "sampling": {
                "mode": "stratified",
                "fields": ["economic_motivation"],
                "allocation": "proportional",
                "sampleSize": 20,
                "portions": {"economic_motivation": {"Cost-sensitive": 0.7, "Premium-seeking": 0.3}},
            },
        }
    )
    assert payload["sampling"]["portions"] == {
        "economic_motivation": {"Cost-sensitive": 0.7, "Premium-seeking": 0.3}
    }


def test_normalize_weighted_filters_become_portions() -> None:
    payload = normalize_persona_strategy(
        {
            "schemaVersion": "1.0",
            "dimensionFilters": {
                "company_size": {"Startup (<50)": None, "SMB (50-500)": None},
                "economic_motivation": {
                    "Cost-sensitive": 0.5,
                    "Value-driven": 0.3,
                    "Premium-seeking": 0.2,
                },
            },
            "sampling": {
                "mode": "stratified",
                "fields": ["economic_motivation"],
                "allocation": "proportional",
                "sampleSize": 20,
            },
        }
    )
    assert payload["dimensionFilters"]["company_size"] == ["Startup (<50)", "SMB (50-500)"]
    assert payload["dimensionFilters"]["economic_motivation"] == [
        "Cost-sensitive",
        "Value-driven",
        "Premium-seeking",
    ]
    assert payload["sampling"]["portions"] == {
        "economic_motivation": {
            "Cost-sensitive": 0.5,
            "Value-driven": 0.3,
            "Premium-seeking": 0.2,
        }
    }
    assert "company_size" not in payload["sampling"]["portions"]


def test_validate_weighted_filters_require_proportional(tmp_path) -> None:
    (tmp_path / "persona_strategy.json").write_text(
        json.dumps(
            {
                "schemaVersion": "1.0",
                "dimensionFilters": {
                    "economic_motivation": {"Cost-sensitive": 0.7, "Premium-seeking": 0.3}
                },
                "sampling": {
                    "mode": "stratified",
                    "fields": ["economic_motivation"],
                    "allocation": "perCell",
                    "perCell": 2,
                },
            }
        ),
        encoding="utf-8",
    )
    errors = validate_persona_strategy_file(tmp_path)
    assert any("dimensionFilters mix weights" in err for err in errors)


def test_sampling_to_pool_kwargs_emits_portions() -> None:
    from backend.service.persona_strategy import sampling_to_pool_kwargs

    out = sampling_to_pool_kwargs(
        {
            "mode": "stratified",
            "fields": ["economic_motivation"],
            "allocation": "proportional",
            "sampleSize": 10,
            "portions": {"economic_motivation": {"Cost-sensitive": 0.7, "Premium-seeking": 0.3}},
        }
    )
    assert out["portions"] == {
        "economic_motivation": {"Cost-sensitive": 0.7, "Premium-seeking": 0.3}
    }


def test_validate_portions_requires_proportional(tmp_path) -> None:
    (tmp_path / "persona_strategy.json").write_text(
        json.dumps(
            {
                "schemaVersion": "1.0",
                "dimensionFilters": {"economic_motivation": ["Cost-sensitive", "Premium-seeking"]},
                "sampling": {
                    "mode": "stratified",
                    "fields": ["economic_motivation"],
                    "allocation": "perCell",
                    "perCell": 2,
                    "portions": {"economic_motivation": {"Cost-sensitive": 0.7}},
                },
            }
        ),
        encoding="utf-8",
    )
    errors = validate_persona_strategy_file(tmp_path)
    assert any('mix weights are only valid with allocation "proportional"' in err for err in errors)


def test_validate_portions_dimension_must_be_a_field(tmp_path) -> None:
    (tmp_path / "persona_strategy.json").write_text(
        json.dumps(
            {
                "schemaVersion": "1.0",
                "dimensionFilters": {"economic_motivation": ["Cost-sensitive", "Premium-seeking"]},
                "sampling": {
                    "mode": "stratified",
                    "fields": ["economic_motivation"],
                    "allocation": "proportional",
                    "sampleSize": 10,
                    "portions": {"region": {"North America": 0.7, "Western Europe": 0.3}},
                },
            }
        ),
        encoding="utf-8",
    )
    errors = validate_persona_strategy_file(tmp_path)
    assert any("portions dimension 'region'" in err for err in errors)


def test_validate_portions_rejects_nonpositive_weight(tmp_path) -> None:
    (tmp_path / "persona_strategy.json").write_text(
        json.dumps(
            {
                "schemaVersion": "1.0",
                "dimensionFilters": {"economic_motivation": ["Cost-sensitive", "Premium-seeking"]},
                "sampling": {
                    "mode": "stratified",
                    "fields": ["economic_motivation"],
                    "allocation": "proportional",
                    "sampleSize": 10,
                    "portions": {"economic_motivation": {"Cost-sensitive": 0.7, "Premium-seeking": -1}},
                },
            }
        ),
        encoding="utf-8",
    )
    errors = validate_persona_strategy_file(tmp_path)
    assert any("must be a positive number" in err for err in errors)


def test_normalize_per_cell_sampling() -> None:
    payload = normalize_persona_strategy(
        {
            "schemaVersion": "1.0",
            "dimensionFilters": {"age_bracket": ["25-34"]},
            "sampling": {
                "mode": "stratified",
                "fields": ["age_bracket"],
                "allocation": "perCell",
                "perCell": 2,
            },
        }
    )
    assert payload["sampling"]["allocation"] == "perCell"
    assert payload["sampling"]["perCell"] == 2


def test_validate_persona_strategy_rejects_legacy_flat_fields(tmp_path) -> None:
    (tmp_path / "persona_strategy.json").write_text(
        json.dumps(
            {
                "schemaVersion": "1.0",
                "defaultMode": "stratified",
                "dimensionFilters": {
                    "age_bracket": ["25-34", "35-44"],
                    "region": ["North America"],
                },
                "stratifyFields": ["age_bracket", "region"],
                "sampleSize": 8,
            }
        ),
        encoding="utf-8",
    )
    errors = validate_persona_strategy_file(tmp_path)
    assert any("remove legacy fields" in err for err in errors)
    assert any("defaultMode" in err for err in errors)


def test_validate_persona_strategy_rejects_both_quota_fields(tmp_path) -> None:
    (tmp_path / "persona_strategy.json").write_text(
        json.dumps(
            {
                "schemaVersion": "1.0",
                "dimensionFilters": {
                    "age_bracket": ["25-34", "35-44"],
                    "region": ["North America"],
                },
                "sampling": {
                    "mode": "stratified",
                    "fields": ["age_bracket", "region"],
                    "allocation": "perCell",
                    "perCell": 2,
                    "sampleSize": 8,
                },
            }
        ),
        encoding="utf-8",
    )
    errors = validate_persona_strategy_file(tmp_path)
    assert any("must not set sampling.sampleSize" in err for err in errors)


def test_load_persona_strategy_missing_file_returns_none(tmp_path) -> None:
    assert load_persona_strategy(tmp_path) is None


def test_validate_persona_strategy_requires_file(tmp_path) -> None:
    errors = validate_persona_strategy_file(tmp_path)
    assert any("missing required persona_strategy.json" in err for err in errors)


def test_validate_persona_strategy_requires_cohort(tmp_path) -> None:
    (tmp_path / "persona_strategy.json").write_text(
        json.dumps(
            {
                "schemaVersion": "1.0",
                "sampling": {"mode": "random", "sampleSize": 4},
                "dimensionFilters": {},
            }
        ),
        encoding="utf-8",
    )
    errors = validate_persona_strategy_file(tmp_path, require_cohort=True)
    assert any("target cohort" in err for err in errors)

    errors_relaxed = validate_persona_strategy_file(tmp_path, require_cohort=False)
    assert errors_relaxed == []


def test_validate_persona_strategy_stratified_needs_axes(tmp_path) -> None:
    (tmp_path / "persona_strategy.json").write_text(
        json.dumps(
            {
                "schemaVersion": "1.0",
                "sampling": {
                    "mode": "stratified",
                    "allocation": "equalTotal",
                    "sampleSize": 4,
                },
                "dimensionFilters": {"region": ["Oceania"]},
            }
        ),
        encoding="utf-8",
    )
    errors = validate_persona_strategy_file(tmp_path)
    assert any("sampling.fields" in err for err in errors)


def test_validate_persona_strategy_stratified_axes_in_filters(tmp_path) -> None:
    (tmp_path / "persona_strategy.json").write_text(
        json.dumps(
            {
                "schemaVersion": "1.0",
                "sampling": {
                    "mode": "stratified",
                    "fields": ["economic_motivation", "life_stage"],
                    "allocation": "equalTotal",
                    "sampleSize": 4,
                },
                "dimensionFilters": {"life_stage": ["Early career"]},
            }
        ),
        encoding="utf-8",
    )
    errors = validate_persona_strategy_file(tmp_path)
    assert any("dimensionFilters" in err and "economic_motivation" in err for err in errors)


def test_validate_persona_strategy_sample_size_covers_cells(tmp_path) -> None:
    (tmp_path / "persona_strategy.json").write_text(
        json.dumps(
            {
                "schemaVersion": "1.0",
                "sampling": {
                    "mode": "stratified",
                    "fields": ["economic_motivation", "life_stage"],
                    "allocation": "equalTotal",
                    "sampleSize": 3,
                },
                "dimensionFilters": {
                    "life_stage": ["Early career", "Mid-life"],
                    "economic_motivation": ["Cost-sensitive", "Indifferent"],
                },
            }
        ),
        encoding="utf-8",
    )
    errors = validate_persona_strategy_file(tmp_path)
    assert any("sampleSize=3" in err and "cell count=4" in err for err in errors)


def test_get_task_detail_includes_persona_strategy(tmp_path) -> None:
    task_dir = tmp_path / "application" / "tasks" / "example-survey-demo"
    task_dir.mkdir(parents=True)
    (task_dir / "task.toml").write_text(
        '[metadata]\ntype = "survey"\n[task]\nname = "demo/survey"\n',
        encoding="utf-8",
    )
    (task_dir / "instruction.md").write_text("# Demo\n\nAnswer in character.\n", encoding="utf-8")
    (task_dir / "persona_strategy.json").write_text(
        json.dumps(
            {
                "schemaVersion": "1.0",
                "dimensionFilters": {"age_bracket": ["18-24", "25-34"]},
                "sampling": {"mode": "random", "sampleSize": 6},
            }
        ),
        encoding="utf-8",
    )

    detail = get_task_detail("application/tasks/example-survey-demo", repo_root=tmp_path)
    assert detail["personaStrategy"] is not None
    assert detail["personaStrategy"]["sampling"]["mode"] == "random"
    assert detail["personaStrategy"]["sampling"]["sampleSize"] == 6
    assert detail["personaStrategy"]["dimensionFilters"]["age_bracket"] == ["18-24", "25-34"]
