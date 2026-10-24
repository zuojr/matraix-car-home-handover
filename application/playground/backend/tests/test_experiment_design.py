"""Tests for the pure experiment design-expansion engine."""

from __future__ import annotations

from backend.service.experiment_design import expand_design, normalize_factors


FACTORS = [
    {
        "id": "target_url",
        "label": "Target",
        "levels": [
            {"id": "prod", "baseline": True, "params": {"target_url": "https://prod"}},
            {"id": "staging1", "params": {"target_url": "https://staging1"}},
        ],
    },
    {
        "id": "content_build",
        "label": "Build",
        "levels": [
            {"id": "a", "baseline": True, "params": {"content_build": "a"}},
            {"id": "b", "params": {"content_build": "b"}},
            {"id": "c", "params": {"content_build": "c"}},
        ],
    },
]


def _baseline_cells(result):
    return [c for c in result["cells"] if c["baseline"]]


def test_full_factorial_is_cartesian_product():
    result = expand_design(FACTORS, design_type="full_factorial")
    assert result["effectiveType"] == "full_factorial"
    assert len(result["cells"]) == 2 * 3  # 6 cells
    assert len(_baseline_cells(result)) == 1
    # params are merged per cell
    for cell in result["cells"]:
        assert set(cell["params"]) == {"target_url", "content_build"}


def test_full_factorial_baseline_cell_uses_all_baseline_levels():
    result = expand_design(FACTORS, design_type="full_factorial")
    (baseline,) = _baseline_cells(result)
    assert baseline["factorLevels"] == {"target_url": "prod", "content_build": "a"}


def test_ab_n_is_one_factor_at_a_time():
    result = expand_design(FACTORS, design_type="ab_n")
    # baseline + (2-1) target levels + (3-1) build levels = 1 + 1 + 2 = 4
    assert len(result["cells"]) == 4
    assert len(_baseline_cells(result)) == 1
    # every non-baseline cell differs from baseline in exactly one factor
    for cell in result["cells"]:
        if cell["baseline"]:
            continue
        diffs = [fid for fid, lid in cell["factorLevels"].items() if lid not in ("prod", "a")]
        assert len(diffs) == 1


def test_fractional_two_level_uses_orthogonal_array():
    three_two_level = [
        {"id": "f1", "levels": [{"id": "lo", "baseline": True, "params": {"f1": 0}}, {"id": "hi", "params": {"f1": 1}}]},
        {"id": "f2", "levels": [{"id": "lo", "baseline": True, "params": {"f2": 0}}, {"id": "hi", "params": {"f2": 1}}]},
        {"id": "f3", "levels": [{"id": "lo", "baseline": True, "params": {"f3": 0}}, {"id": "hi", "params": {"f3": 1}}]},
    ]
    result = expand_design(three_two_level, design_type="fractional")
    assert result["effectiveType"] == "fractional"
    assert len(result["cells"]) == 4  # L4, vs 8 for full factorial
    assert len(_baseline_cells(result)) == 1


def test_fractional_falls_back_to_full_when_not_two_level():
    result = expand_design(FACTORS, design_type="fractional")
    assert result["effectiveType"] == "full_factorial"
    assert len(result["cells"]) == 6


def test_selected_factors_subsets_and_orders():
    result = expand_design(FACTORS, design_type="full_factorial", selected_factors=["content_build"])
    assert [f["id"] for f in result["factors"]] == ["content_build"]
    assert len(result["cells"]) == 3


def test_unknown_factor_raises():
    try:
        normalize_factors(FACTORS, selected=["nope"])
    except ValueError as exc:
        assert "nope" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")
