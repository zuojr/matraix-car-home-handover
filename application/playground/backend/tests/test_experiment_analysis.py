"""Tests for the experiment analysis engine (tests, pairing, BH)."""

from __future__ import annotations

from backend.service.experiment_analysis import (
    analyze_experiment,
    analyze_persona_slices,
    benjamini_hochberg,
    discover_sliceable_dimensions,
    extract_metrics,
    paired_persona_deltas,
    _infer_numeric_scale,
)


def _arm(cell_id, baseline, trials):
    return {"cellId": cell_id, "arm": cell_id, "baseline": baseline, "trials": trials}


def _numeric_trials(prefix, values):
    return [
        {"personaId": f"{prefix}{i}", "pairId": str(i), "metrics": {"rating": v}}
        for i, v in enumerate(values)
    ]


def test_extract_metrics_pulls_facet_keys():
    so = {
        "contexts": [
            {"facets": [{"key": "chosen_option", "value": "Plus"}, {"key": "ignore", "value": 1}]},
            {"facets": [{"key": "overall_experience_rating", "value": 8}]},
        ]
    }
    out = extract_metrics(so, ["chosen_option", "overall_experience_rating"])
    assert out == {"chosen_option": "Plus", "overall_experience_rating": 8}


def test_infer_numeric_scale_covers_common_metric_shapes():
    assert _infer_numeric_scale([0, 1, 1, 0, 1]) == "binary"
    assert _infer_numeric_scale([1, 2, 3, 4, 5, 6, 7]) == "score"
    assert _infer_numeric_scale([0, 2, 5, 12, 40]) == "count"
    assert _infer_numeric_scale([0.12, 0.44, 1.3]) == "continuous"


def test_numerical_summary_exposes_sum_and_scale():
    base_vals = [5, 6, 7, 5, 6, 7, 5, 6, 7, 6]
    arm_vals = [v + 1 for v in base_vals]
    arms = [
        _arm("base", True, _numeric_trials("p", base_vals)),
        _arm("treat", False, _numeric_trials("p", arm_vals)),
    ]
    result = analyze_experiment(arms, {"primary": ["rating"]}, metric_kinds={"rating": "numerical"})
    (cmp,) = result["comparisons"]
    assert cmp["scale"] == "score"
    assert cmp["baseline"]["sum"] == sum(base_vals)
    assert cmp["treatment"]["min"] == min(arm_vals)
    assert cmp["effect"]["diff"] == 1.0

    q = benjamini_hochberg([0.01, 0.02, 0.03, 0.04], alpha=0.05)
    assert all(0.0 <= v <= 1.0 for v in q)
    # smallest raw p should have the smallest q
    assert q[0] <= q[-1]


def test_numerical_paired_detects_shift():
    # same personas (pairId) across arms; treatment uniformly +3 -> paired t significant
    base_vals = [5, 6, 7, 5, 6, 7, 5, 6, 7, 6]
    arm_vals = [v + 3 for v in base_vals]
    arms = [
        _arm("base", True, _numeric_trials("p", base_vals)),
        _arm("treat", False, _numeric_trials("p", arm_vals)),
    ]
    contract = {"primary": ["rating"]}
    result = analyze_experiment(arms, contract, metric_kinds={"rating": "numerical"})
    (cmp,) = result["comparisons"]
    assert cmp["test"] == "paired_t"
    assert cmp["paired"] is True
    assert cmp["effect"]["diff"] == 3.0
    assert cmp["pValue"] < 0.001
    assert cmp["significant"] is True


def test_numerical_unpaired_when_no_shared_personas():
    base = [{"personaId": f"a{i}", "metrics": {"rating": v}} for i, v in enumerate([5, 5, 6, 6, 5, 6])]
    treat = [{"personaId": f"b{i}", "metrics": {"rating": v}} for i, v in enumerate([5, 6, 5, 6, 5, 6])]
    arms = [_arm("base", True, base), _arm("treat", False, treat)]
    result = analyze_experiment(arms, {"secondary": ["rating"]}, metric_kinds={"rating": "numerical"})
    (cmp,) = result["comparisons"]
    assert cmp["test"] == "welch_t"
    assert cmp["paired"] is False


def test_categorical_chi_square_detects_distribution_change():
    base = [{"personaId": f"a{i}", "metrics": {"choice": c}} for i, c in enumerate(["free"] * 8 + ["plus"] * 2)]
    treat = [{"personaId": f"b{i}", "metrics": {"choice": c}} for i, c in enumerate(["free"] * 2 + ["plus"] * 8)]
    arms = [_arm("base", True, base), _arm("treat", False, treat)]
    result = analyze_experiment(arms, {"primary": ["choice"]}, metric_kinds={"choice": "categorical"})
    (cmp,) = result["comparisons"]
    assert cmp["kind"] == "categorical"
    assert cmp["test"] == "chi_square"
    assert cmp["pValue"] < 0.05
    assert cmp["significant"] is True
    assert set(cmp["categories"]) == {"free", "plus"}


def test_textual_is_skipped():
    base = [{"personaId": "a", "metrics": {"reason": "long text " * 10}}]
    treat = [{"personaId": "b", "metrics": {"reason": "another long text " * 10}}]
    arms = [_arm("base", True, base), _arm("treat", False, treat)]
    result = analyze_experiment(arms, {"secondary": ["reason"]})
    (cmp,) = result["comparisons"]
    assert cmp["kind"] == "textual"
    assert cmp["test"] == "skipped"
    assert cmp["significant"] is False


def test_multiple_metrics_family_correction_counts_only_tested():
    base_vals = [5, 6, 7, 5, 6, 7]
    arms = [
        _arm("base", True, _numeric_trials("p", base_vals)),
        _arm("treat", False, _numeric_trials("p", [v + 2 for v in base_vals])),
    ]
    # rating tested (numerical) + reason skipped (textual)
    for t in arms[0]["trials"]:
        t["metrics"]["reason"] = "x" * 60
    for t in arms[1]["trials"]:
        t["metrics"]["reason"] = "y" * 60
    contract = {"primary": ["rating"], "secondary": ["reason"]}
    result = analyze_experiment(arms, contract, metric_kinds={"rating": "numerical", "reason": "textual"})
    assert result["correction"]["count"] == 1  # only the numerical metric was tested
    assert result["correction"]["method"] == "none"


def test_fdr_off_by_default_uses_raw_p_for_significance():
    base_vals = [5, 6, 7, 5, 6, 7, 5, 6, 7, 6]
    arms = [
        _arm("base", True, _numeric_trials("p", base_vals)),
        _arm("treat", False, _numeric_trials("p", [v + 3 for v in base_vals])),
    ]
    result = analyze_experiment(
        arms,
        {"primary": ["rating"]},
        metric_kinds={"rating": "numerical"},
        multiple_testing="none",
    )
    assert result["correction"]["method"] == "none"
    (cmp,) = result["comparisons"]
    assert cmp["pValue"] < 0.05
    assert cmp["significant"] is True
    assert isinstance(cmp["pValueAdj"], float)


def test_fdr_bh_uses_adjusted_p_for_significance():
    # Many noisy secondaries inflate BH; a borderline primary may lose significance.
    rng_base = list(range(20))
    base = [{"personaId": f"p{i}", "pairId": str(i), "metrics": {"rating": 5 + (i % 3) * 0.1}} for i in rng_base]
    treat = [
        {
            "personaId": f"p{i}",
            "pairId": str(i),
            "metrics": {
                "rating": 5.15 + (i % 3) * 0.1,
                **{f"noise{j}": 1.0 + (i + j) % 5 * 0.01 for j in range(8)},
            },
        }
        for i in rng_base
    ]
    for t in base:
        for j in range(8):
            t["metrics"][f"noise{j}"] = 1.0 + (int(t["pairId"]) + j) % 5 * 0.01
    arms = [_arm("base", True, base), _arm("treat", False, treat)]
    contract = {
        "primary": ["rating"],
        "secondary": [f"noise{j}" for j in range(8)],
    }
    kinds = {k: "numerical" for k in ["rating", *[f"noise{j}" for j in range(8)]]}
    uncorrected = analyze_experiment(arms, contract, metric_kinds=kinds, multiple_testing="none", alpha=0.05)
    corrected = analyze_experiment(arms, contract, metric_kinds=kinds, multiple_testing="bh", alpha=0.05)
    assert uncorrected["correction"]["method"] == "none"
    assert corrected["correction"]["method"] == "benjamini_hochberg"
    assert corrected["correction"]["count"] == 9
    # With FDR on, significance is never looser than uncorrected.
    for u, c in zip(uncorrected["comparisons"], corrected["comparisons"]):
        if c["significant"]:
            assert u["significant"] is True

def test_discover_sliceable_dimensions_skips_traits_and_singletons():
    arms = [
        _arm(
            "base",
            True,
            [
                {
                    "personaId": "a",
                    "metrics": {},
                    "dimensions": {
                        "urbanicity": "City",
                        "trait_kindness": "Slight",
                        "trust_level": "Trusting",
                    },
                },
                {
                    "personaId": "b",
                    "metrics": {},
                    "dimensions": {
                        "urbanicity": "Town",
                        "trait_kindness": "Slight",
                        "trust_level": "Trusting",
                    },
                },
            ],
        )
    ]
    dims = discover_sliceable_dimensions(arms)
    ids = {d["id"] for d in dims}
    assert "urbanicity" in ids
    assert "trait_kindness" not in ids
    assert "trust_level" not in ids  # only one distinct value


def test_analyze_persona_slices_detects_heterogeneous_lift():
    base = []
    treat = []
    for i in range(8):
        base.append(
            {
                "personaId": f"p{i}",
                "pairId": str(i),
                "metrics": {"rating": 5.0, "guard": 1.0},
                "dimensions": {"urbanicity": "City" if i < 4 else "Town"},
            }
        )
        treat.append(
            {
                "personaId": f"p{i}",
                "pairId": str(i),
                "metrics": {
                    "rating": 8.0 if i < 4 else 5.0,
                    "guard": 0.5 if i < 4 else 1.0,
                },
                "dimensions": {"urbanicity": "City" if i < 4 else "Town"},
            }
        )
    arms = [_arm("base", True, base), _arm("treat", False, treat)]
    contract = {"primary": ["rating"], "guardrail": ["guard"]}
    out = analyze_persona_slices(
        arms,
        contract,
        dimension="urbanicity",
        metric_key="rating",
        metric_kinds={"rating": "numerical", "guard": "numerical"},
        min_n=3,
    )
    by_val = {r["value"]: r for r in out["rows"]}
    assert by_val["City"]["effect"]["diff"] == 3.0
    assert by_val["Town"]["effect"]["diff"] == 0.0
    assert by_val["City"]["guardrails"][0]["metricKey"] == "guard"
    assert by_val["City"]["guardrails"][0]["diff"] == -0.5


def test_paired_persona_deltas_lists_who_got_worse():
    base = _numeric_trials("p", [5, 6, 7, 8])
    treat = _numeric_trials("p", [4, 6, 9, 10])  # -1, 0, +2, +2
    arms = [_arm("base", True, base), _arm("treat", False, treat)]
    out = paired_persona_deltas(arms, "rating", limit=10)
    assert out is not None
    assert out["paired"] is True
    assert out["unchanged"] == 1
    assert len(out["worse"]) == 1
    assert out["worse"][0]["diff"] == -1.0
    assert len(out["better"]) == 2


def test_rank_persona_drivers_surfaces_heterogeneous_attribute():
    from backend.service.experiment_analysis import rank_persona_drivers

    base, treat = [], []
    for i in range(12):
        city = i < 6
        base.append(
            {
                "personaId": f"p{i}",
                "pairId": str(i),
                "metrics": {"rating": 5.0},
                "dimensions": {
                    "urbanicity": "City" if city else "Town",
                    "trust_level": "Trusting",
                },
            }
        )
        treat.append(
            {
                "personaId": f"p{i}",
                "pairId": str(i),
                "metrics": {"rating": 8.0 if city else 5.0},
                "dimensions": {
                    "urbanicity": "City" if city else "Town",
                    "trust_level": "Trusting",
                },
            }
        )
    arms = [_arm("base", True, base), _arm("treat", False, treat)]
    drivers = rank_persona_drivers(
        arms,
        {"primary": ["rating"]},
        metric_key="rating",
        candidate_dimensions=["trust_level", "urbanicity"],
        metric_kinds={"rating": "numerical"},
        min_n=3,
    )
    assert drivers
    assert drivers[0]["dimension"] == "urbanicity"
    assert drivers[0]["highest"]["value"] == "City"
    assert drivers[0]["lowest"]["value"] == "Town"


def test_rank_persona_drivers_returns_per_treatment_arm():
    from backend.service.experiment_analysis import rank_persona_drivers

    def make_trials(prefix, city_boost):
        out = []
        for i in range(12):
            city = i < 6
            out.append(
                {
                    "personaId": f"{prefix}{i}",
                    "pairId": str(i),
                    "metrics": {"rating": (8.0 if city else 5.0) if city_boost else (5.0 if city else 7.0)},
                    "dimensions": {"urbanicity": "City" if city else "Town"},
                }
            )
        return out

    base = [
        {
            "personaId": f"b{i}",
            "pairId": str(i),
            "metrics": {"rating": 5.0},
            "dimensions": {"urbanicity": "City" if i < 6 else "Town"},
        }
        for i in range(12)
    ]
    arms = [
        _arm("base", True, base),
        _arm("treat_a", False, make_trials("a", True)),   # City high
        _arm("treat_b", False, make_trials("b", False)),  # Town high
    ]
    drivers = rank_persona_drivers(
        arms,
        {"primary": ["rating"]},
        metric_key="rating",
        candidate_dimensions=["urbanicity"],
        metric_kinds={"rating": "numerical"},
        min_n=3,
        top_k=3,
    )
    by_arm = {d["cellId"]: d for d in drivers}
    assert "treat_a" in by_arm and "treat_b" in by_arm
    assert by_arm["treat_a"]["highest"]["value"] == "City"
    assert by_arm["treat_b"]["highest"]["value"] == "Town"
