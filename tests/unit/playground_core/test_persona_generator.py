"""Tests for synthetic persona consistency and generation."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from matraix.persona_consistency import validate_dimensions
from matraix.persona_generator import generate_persona_pool

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = REPO_ROOT / "persona" / "datasets" / "matraix-persona-dev-sample" / "manifest.json"


def test_generate_dimensions_respects_fixed_life_stage_without_age() -> None:
    """Fixed life_stage must pick a compatible age (no empty seniority lists)."""
    import random

    from matraix.persona_consistency import LIFE_STAGE_BY_AGE, validate_dimensions
    from matraix.persona_generator import (
        generate_persona_dimensions,
        load_catalog_values,
    )
    from matraix.persona_consistency import load_dev_dimension_ids

    catalog = load_catalog_values()
    dev_ids = load_dev_dimension_ids()
    rng = random.Random(0)
    for life_stage in ("Student", "Mid-life", "Career change", "Retirement"):
        dims = generate_persona_dimensions(
            rng=rng,
            catalog=catalog,
            dev_dimension_ids=dev_ids,
            fixed_dimensions={"life_stage": life_stage, "values_priority": "Autonomy"},
        )
        assert dims["life_stage"] == life_stage
        assert life_stage in LIFE_STAGE_BY_AGE[dims["age_bracket"]]
        assert validate_dimensions(dims) == []


def test_validate_rejects_counterfactual_combo() -> None:
    errors = validate_dimensions(
        {
            "age_bracket": "18-24",
            "life_stage": "Retirement",
            "seniority": "Retired",
            "years_experience": "20+",
            "highest_education": "Secondary",
        }
    )
    assert errors
    assert any("life_stage" in err for err in errors)


def test_validate_accepts_v2_age_bracket_dash_style() -> None:
    assert (
        validate_dimensions(
            {
                "age_bracket": "18–24",
                "life_stage": "Early career",
                "seniority": "Entry",
                "years_experience": "0-2",
                "highest_education": "Bachelor's",
            }
        )
        == []
    )


def test_dev_dimension_ids_include_core_catalog_fields() -> None:
    from matraix.persona_consistency import load_dev_dimension_ids

    dev_ids = set(load_dev_dimension_ids())

    assert {
        "age_bracket",
        "socioeconomic_band",
        "tech_savviness",
        "risk_tolerance",
        "economic_motivation",
        "lstyle_diet_type",
        "health_dietary_restriction",
        "habit_meal_prepping",
        "habit_skipping_breakfast",
        "habit_late_night_snacking",
        "att_veganism",
        "fam_nutrition",
    } <= dev_ids
    assert any(dim_id.startswith("cuis_") for dim_id in dev_ids)
    assert len(dev_ids) == 124


def test_generate_pool_is_synthetic_full_dag() -> None:
    personas = generate_persona_pool(count=50, seed=99)
    for entry in personas:
        assert entry.get("source") == "synthetic"
        assert entry.get("version") == "1.0"
        assert len(entry["dimensions"]) >= 1000
        assert "age_bracket" in entry["dimensions"]
        assert "lstyle_diet_type" in entry["dimensions"]
        assert "health_dietary_restriction" in entry["dimensions"]
        assert "habit_meal_prepping" in entry["dimensions"]
        assert any(key.startswith("cuis_") for key in entry["dimensions"])


def test_top_up_strata_fills_filter_cells() -> None:
    from matraix.persona_generator import (
        build_probe_strata,
        generate_persona_pool,
        top_up_strata,
    )

    confounders = {
        "socioeconomic_band": "Middle",
        "age_bracket": "25-34",
        "risk_tolerance": "Balanced",
        "tech_savviness": "Comfortable",
    }
    strata = build_probe_strata(
        confounders=confounders,
        probe_dimension="dimensions.economic_motivation",
        probe_values=["Cost-sensitive", "Indifferent"],
    )
    personas = generate_persona_pool(count=50, seed=1, smoke_persona_id="0001")
    topped = top_up_strata(
        personas,
        strata=strata,
        min_per_stratum=2,
        seed=99,
    )
    assert len(topped) > len(personas)
    for stratum in strata:
        matches = [
            entry
            for entry in topped
            if all(entry["dimensions"].get(k) == v for k, v in stratum.items())
        ]
        assert len(matches) >= 2
        for entry in matches:
            assert entry.get("source") == "synthetic"


def test_build_filter_strata_cartesian() -> None:
    from matraix.persona_generator import build_filter_strata

    strata = build_filter_strata(
        {
            "age_bracket": ["25-34", "35-44"],
            "life_stage": ["Early career"],
        }
    )
    assert len(strata) == 2
    assert {"age_bracket": "25-34", "life_stage": "Early career"} in strata
    assert {"age_bracket": "35-44", "life_stage": "Early career"} in strata


def test_independent_marginal_quotas_equal_and_weighted() -> None:
    from matraix.persona_generator import independent_marginal_cell_quotas

    filters = {
        "age_bracket": ["18-24", "25-34", "35-44", "45-54"],
        "gender_identity": ["Man", "Woman"],
    }
    cells = [
        {"age_bracket": age, "gender_identity": gender}
        for age in filters["age_bracket"]
        for gender in filters["gender_identity"]
    ]
    equal = independent_marginal_cell_quotas(cells, 32, dimension_filters=filters)
    assert sum(equal) == 32
    assert equal == [4] * 8

    weighted = independent_marginal_cell_quotas(
        cells,
        32,
        dimension_filters=filters,
        marginals={"gender_identity": {"Man": 3, "Woman": 1}},
    )
    assert sum(weighted) == 32
    man = sum(
        quota
        for cell, quota in zip(cells, weighted, strict=True)
        if cell["gender_identity"] == "Man"
    )
    woman = 32 - man
    assert man == 24
    assert woman == 8


def test_normalize_and_stamp_study_overlay() -> None:
    from matraix.persona_generator import (
        fill_overlay_filters,
        normalize_overlay_dimensions,
        split_overlay_filters,
        stamp_overlay_from_cells,
        stamp_overlay_independent,
    )

    overlay = normalize_overlay_dimensions(
        [{"id": "study_trust", "label": "Trust", "values": ["Low", "High"]}]
    )
    catalog, overlay_filters = split_overlay_filters(
        {"age_bracket": ["25-34"], "study_trust": ["Low"]},
        {"study_trust"},
    )
    assert catalog == {"age_bracket": ["25-34"]}
    assert overlay_filters == {"study_trust": ["Low"]}
    filled = fill_overlay_filters(overlay, {})
    assert filled["study_trust"] == ["Low", "High"]

    personas = [
        {"persona_id": "0001", "dimensions": {"age_bracket": "25-34"}},
        {"persona_id": "0002", "dimensions": {"age_bracket": "25-34"}},
    ]
    stamp_overlay_from_cells(
        personas,
        [
            {"age_bracket": "25-34", "study_trust": "Low"},
            {"age_bracket": "25-34", "study_trust": "High"},
        ],
        [1, 1],
        {"study_trust"},
    )
    values = {entry["dimensions"]["study_trust"] for entry in personas}
    assert values == {"Low", "High"}

    independent = [{"persona_id": "0003", "dimensions": {}}]
    stamp_overlay_independent(independent, overlay, filled, seed=1)
    assert independent[0]["dimensions"]["study_trust"] in {"Low", "High"}


def test_generate_persona_pool_extra_filters_pin_catalog_dims() -> None:
    from matraix import persona_generator as gen

    class FakeDag:
        def assignment_supported(self, pinned: dict[str, str]) -> bool:
            return True

        def sample(self, n: int, *, fixed: dict[str, str] | None = None):
            base = {"age_bracket": "18-24", "region": "US"}
            if fixed:
                base.update(fixed)
            return [dict(base) for _ in range(n)]

    original = gen._dag_sampler
    gen._dag_sampler = lambda **kwargs: FakeDag()
    try:
        personas = gen.generate_persona_pool(
            count=3,
            seed=1,
            extra_filters={"age_bracket": ["25-34"]},
            include_smoke=False,
        )
    finally:
        gen._dag_sampler = original

    assert len(personas) == 3
    assert {row["dimensions"]["age_bracket"] for row in personas} == {"25-34"}


def test_stratified_cell_quota_matches_playground_allocations() -> None:
    import pytest

    from matraix.persona_generator import stratified_cell_quota

    assert (
        stratified_cell_quota(
            allocation="perCell", per_cell=4, sample_size=None, n_cells=10
        )
        == 4
    )
    assert (
        stratified_cell_quota(
            allocation="equalTotal", per_cell=None, sample_size=8, n_cells=3
        )
        == 3
    )
    assert (
        stratified_cell_quota(
            allocation="proportional", per_cell=None, sample_size=8, n_cells=3
        )
        == 3
    )
    with pytest.raises(ValueError, match="below the stratified cell count"):
        stratified_cell_quota(
            allocation="equalTotal", per_cell=None, sample_size=2, n_cells=5
        )


def test_strategy_pin_cells_keeps_stratify_axes_only() -> None:
    from matraix.persona_generator import strategy_pin_cells

    cells, _dropped = strategy_pin_cells(
        dimension_filters={
            "age_bracket": ["25-34", "35-44"],
            "life_stage": ["Early career", "Mid-life"],
        },
        stratify_fields=["life_stage"],
        seed=1,
    )
    assert cells
    for cell in cells:
        assert cell["life_stage"] in {"Early career", "Mid-life"}
        assert "age_bracket" not in cell


def test_top_up_randomizes_non_stratify_filters() -> None:
    from matraix.persona_generator import generate_persona_pool

    ages = ["18-24", "25-34", "35-44", "45-54"]
    personas = generate_persona_pool(
        count=0,
        seed=7,
        stratum_top_up=[{"age_bracket": age} for age in ages],
        min_per_stratum=4,
        extra_filters={"gender_identity": ["Man", "Woman"]},
        include_smoke=False,
    )
    seen_ages = {entry["dimensions"]["age_bracket"] for entry in personas}
    seen_genders = {entry["dimensions"]["gender_identity"] for entry in personas}
    assert seen_ages <= set(ages)
    assert "13-17" not in seen_ages
    assert "55-64" not in seen_ages
    assert seen_genders <= {"Man", "Woman"}
    assert seen_genders == {"Man", "Woman"}


def test_generate_pool_strategy_top_up_only() -> None:
    from matraix.persona_generator import (
        build_filter_strata,
        generate_persona_pool,
    )

    strata = build_filter_strata(
        {
            "age_bracket": ["25-34", "35-44"],
            "life_stage": ["Early career", "Mid-life"],
        }
    )
    personas = generate_persona_pool(
        count=0,
        seed=7,
        stratum_top_up=strata,
        min_per_stratum=2,
        include_smoke=False,
    )
    filled = 0
    for stratum in strata:
        matches = [
            entry
            for entry in personas
            if all(entry["dimensions"].get(k) == v for k, v in stratum.items())
        ]
        if not matches:
            continue
        filled += 1
        assert len(matches) >= 2
        for entry in matches:
            assert entry.get("source") == "synthetic"
    assert filled >= 1
    assert len(personas) >= 2 * filled


def test_checked_in_sample_manifest_is_consistent() -> None:
    """The dev sample is a slice of matraix-persona-1m, not generator output.

    Real personas carry a sparse subset of the catalog and legitimately break the
    synthetic generator's coherence rules, so only catalog membership is checked.
    """
    from matraix.persona_generator import load_catalog_values

    catalog_ids = set(load_catalog_values())
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["count"] == len(manifest["personas"])
    assert manifest["count"] >= 2
    assert manifest.get("schema_version") == "1.0"
    assert manifest.get("dimension_count") == len(manifest["dimension_ids"])
    assert set(manifest["dimension_ids"]) == catalog_ids
    assert str(manifest.get("parent_pool", "")).endswith("matraix-persona-1m")

    sources = set(manifest["source_counts"])
    assert sum(manifest["source_counts"].values()) == manifest["count"]
    for entry in manifest["personas"]:
        rel_path = entry if isinstance(entry, str) else entry["path"]
        if not isinstance(rel_path, str):
            rel_path = rel_path.split("/")[-1]
        yaml_path = MANIFEST.parent / Path(rel_path).name
        payload = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        assert payload.get("version") == "1.0"
        assert payload.get("source") in sources
        assert payload["dimensions"]
        assert set(payload["dimensions"]) <= catalog_ids


def test_parse_overlay_and_filter_cli() -> None:
    from matraix.persona_generator import (
        normalize_overlay_dimensions,
        parse_filter_cli,
        parse_marginal_cli,
        parse_overlay_cli,
    )

    row = normalize_overlay_dimensions(
        [parse_overlay_cli("brand_trust:Brand trust=Low,High")]
    )[0]
    assert row["id"] == "brand_trust"
    assert row["label"] == "Brand trust"
    assert row["values"] == ["Low", "High"]
    dim, values = parse_filter_cli("age_bracket=25-34,35-44")
    assert dim == "age_bracket"
    assert values == ["25-34", "35-44"]
    mdim, weights = parse_marginal_cli("gender_identity=Man:70,Woman:30")
    assert mdim == "gender_identity"
    assert weights == {"Man": 70.0, "Woman": 30.0}


def test_overlay_manifest_uses_snake_case_only() -> None:
    from matraix.persona_generator import overlay_dimensions_from_manifest

    assert overlay_dimensions_from_manifest(
        {"overlayDimensions": [{"id": "x", "values": ["a"]}]}
    ) == []
    parsed = overlay_dimensions_from_manifest(
        {"overlay_dimensions": [{"id": "x", "label": "X", "values": ["a"]}]}
    )
    assert parsed == [{"id": "x", "label": "X", "values": ["a"]}]


def test_generate_synthetic_personas_stamps_overlay() -> None:
    from matraix import persona_generator as gen

    class FakeDag:
        def assignment_supported(self, pinned: dict[str, str]) -> bool:
            return True

        def sample(self, n: int, *, fixed: dict[str, str] | None = None):
            base = {"age_bracket": "18-24"}
            if fixed:
                base.update(fixed)
            return [dict(base) for _ in range(n)]

    original = gen._dag_sampler
    gen._dag_sampler = lambda **kwargs: FakeDag()
    try:
        result = gen.generate_synthetic_personas(
            count=2,
            seed=1,
            dimension_filters={"age_bracket": ["25-34"]},
            overlay_dimensions=[
                {"id": "study_trust", "label": "Trust", "values": ["Low", "High"]}
            ],
        )
    finally:
        gen._dag_sampler = original

    assert result.folder_count == 2
    assert result.overlay[0]["id"] == "study_trust"
    for row in result.personas:
        assert row["dimensions"]["age_bracket"] == "25-34"
        assert row["dimensions"]["study_trust"] in {"Low", "High"}


def test_generate_synthetic_personas_overlay_per_cell() -> None:
    from collections import Counter

    from matraix import persona_generator as gen

    class FakeDag:
        def assignment_supported(self, pinned: dict[str, str]) -> bool:
            return True

        def sample(self, n: int, *, fixed: dict[str, str] | None = None):
            base = {"age_bracket": "25-34"}
            if fixed:
                base.update(fixed)
            return [dict(base) for _ in range(n)]

    original = gen._dag_sampler
    gen._dag_sampler = lambda **kwargs: FakeDag()
    try:
        result = gen.generate_synthetic_personas(
            seed=1,
            overlay_dimensions=[
                {"id": "study_trust", "label": "Trust", "values": ["Low", "High"]}
            ],
            dimension_filters={"study_trust": ["Low", "High"]},
            stratify_fields=["study_trust"],
            allocation="perCell",
            per_cell=2,
        )
    finally:
        gen._dag_sampler = original

    assert result.folder_count == 4
    counts = Counter(row["dimensions"]["study_trust"] for row in result.personas)
    assert counts["Low"] == 2
    assert counts["High"] == 2


def test_clone_contrast_personas_flips_only_overlay() -> None:
    from matraix.persona_generator import clone_contrast_personas

    cloned = clone_contrast_personas(
        [
            {
                "persona_id": "0001",
                "version": "1.0",
                "source": "synthetic",
                "dimensions": {"age_bracket": "25-34", "study_trust": "High"},
            }
        ],
        overlay_id="study_trust",
        value="Low",
    )
    assert cloned[0]["persona_id"] == "0001-c-low"
    assert cloned[0]["pair_id"] == "0001"
    assert cloned[0]["dimensions"]["age_bracket"] == "25-34"
    assert cloned[0]["dimensions"]["study_trust"] == "Low"


def test_contrast_stamp_combinations_cartesian() -> None:
    from matraix.persona_generator import contrast_stamp_combinations

    combos = contrast_stamp_combinations(
        [
            {"id": "study_trust", "values": ["Low", "High"]},
            {"id": "ad_arm", "values": ["Banner"]},
        ]
    )
    assert combos == [
        {"study_trust": "Low", "ad_arm": "Banner"},
        {"study_trust": "High", "ad_arm": "Banner"},
    ]


def test_normalize_generate_contrast_independent_arms() -> None:
    from matraix.persona_generator import normalize_generate_contrast

    overlay = [
        {"id": "study_trust", "label": "Trust", "values": ["Low", "High"]},
        {"id": "ad_arm", "label": "Ad", "values": ["None", "Banner", "Video"]},
    ]
    plan = normalize_generate_contrast(
        overlay,
        [
            {
                "overlayId": "study_trust",
                "baseValue": "High",
                "values": ["Low", "High"],
            },
            {"overlayId": "ad_arm", "baseValue": "None", "values": ["Banner"]},
        ],
    )
    assert [(arm["id"], arm["base"], arm["values"]) for arm in plan] == [
        ("study_trust", "High", ["Low", "High"]),
        ("ad_arm", "None", ["Banner"]),
    ]


def test_normalize_generate_contrast_requires_overlay() -> None:
    import pytest

    from matraix.persona_generator import normalize_generate_contrast

    with pytest.raises(ValueError, match="custom dimension"):
        normalize_generate_contrast(
            [],
            [{"overlayId": "study_trust", "baseValue": "High", "values": ["Low"]}],
        )


def test_resolve_contrast_overlay_allows_schema_id() -> None:
    from matraix.persona_generator import resolve_contrast_overlay

    row = resolve_contrast_overlay(
        [],
        "age_bracket",
        "25-34",
        schema_ids={"age_bracket"},
    )
    assert row["id"] == "age_bracket"
    assert row["values"] == ["25-34"]


def test_validate_contrast_stamps_against_dag_passes_when_supported() -> None:
    from matraix.persona_generator import validate_contrast_stamps_against_dag

    class FakeDag:
        def assignment_supported(self, pinned: dict[str, str]) -> bool:
            return pinned.get("age_bracket") != "13-17"

    personas = [
        {
            "persona_id": "p1",
            "dimensions": {"age_bracket": "25-34", "region": "US"},
        }
    ]
    validate_contrast_stamps_against_dag(
        personas,
        {"age_bracket": "18-24"},
        schema_ids={"age_bracket", "region"},
        sampler=FakeDag(),
    )


def test_validate_contrast_stamps_against_dag_rejects_hard_mask() -> None:
    import pytest

    from matraix.persona_generator import validate_contrast_stamps_against_dag

    class FakeDag:
        def assignment_supported(self, pinned: dict[str, str]) -> bool:
            return not (
                pinned.get("age_bracket") == "13-17"
                and pinned.get("tool_python") == "Power user"
            )

    personas = [
        {
            "persona_id": "p1",
            "dimensions": {"age_bracket": "13-17", "tool_python": "Never used"},
        }
    ]
    with pytest.raises(ValueError, match="not Full-DAG-supported"):
        validate_contrast_stamps_against_dag(
            personas,
            {"tool_python": "Power user"},
            schema_ids={"age_bracket", "tool_python"},
            sampler=FakeDag(),
        )


def test_validate_contrast_stamps_skips_custom_overlay_dims() -> None:
    from matraix.persona_generator import validate_contrast_stamps_against_dag

    class FakeDag:
        def assignment_supported(self, pinned: dict[str, str]) -> bool:
            raise AssertionError("custom stamps should not hit the DAG")

    personas = [{"persona_id": "p1", "dimensions": {"age_bracket": "25-34"}}]
    validate_contrast_stamps_against_dag(
        personas,
        {"study_trust": "Low"},
        schema_ids={"age_bracket"},
        sampler=FakeDag(),
    )


def test_generate_synthetic_personas_rejects_catalog_id() -> None:
    import pytest

    from matraix.persona_generator import generate_synthetic_personas

    with pytest.raises(ValueError, match="collides"):
        generate_synthetic_personas(
            count=1,
            overlay_dimensions=[{"id": "age_bracket", "label": "Age", "values": ["x"]}],
        )
