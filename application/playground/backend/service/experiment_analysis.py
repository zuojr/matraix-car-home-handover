"""Experiment analysis: compare arms against the baseline on the metric contract.

Operates on already-extracted per-trial metric values (so it stays pure and
testable). For each non-baseline arm and each facet key in the metric contract it:

- picks the right test by metric kind:
  - numerical -> paired t-test when the arms share personas (by ``pairId`` or
    ``personaId``), else Welch's unpaired t-test,
  - categorical -> chi-square test of the arm × category contingency,
  - textual -> skipped (reported, not tested),
- reports effect size (mean diff + Cohen's d, or per-category proportions),
- optionally applies Benjamini-Hochberg FDR across the comparison family
  (``multiple_testing="bh"``; default is uncorrected ``"none"``) and flags
  significance at ``alpha``.

Requires numpy + scipy (available in the backend env).
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

import numpy as np
from scipy import stats


# --------------------------------------------------------------------------
# Helpers for the orchestration layer
# --------------------------------------------------------------------------

def extract_metrics(structured_output: dict[str, Any], wanted: Iterable[str]) -> dict[str, Any]:
    """Pull the requested facet keys out of a trial's structured_output.json.

    Scans every context's facets and returns ``{facetKey: value}`` for keys in
    ``wanted``. Later contexts win on key collision (rare).
    """
    want = set(wanted)
    out: dict[str, Any] = {}
    for context in structured_output.get("contexts") or []:
        if not isinstance(context, dict):
            continue
        for facet in context.get("facets") or []:
            if not isinstance(facet, dict):
                continue
            key = facet.get("key")
            if key in want:
                out[key] = facet.get("value")
    return out


def _roles_for(metric_contract: dict[str, Any]) -> dict[str, str]:
    roles: dict[str, str] = {}
    for role in ("primary", "secondary", "guardrail"):
        for key in metric_contract.get(role) or []:
            roles.setdefault(key, role)
    return roles


def _infer_kind(values: list[Any]) -> str:
    for v in values:
        if v is None:
            continue
        if isinstance(v, bool):
            return "categorical"
        if isinstance(v, (int, float)):
            return "numerical"
        return "categorical" if isinstance(v, str) and len(v) <= 40 else "textual"
    return "categorical"


def _numeric(values: Iterable[Any]) -> list[float]:
    out: list[float] = []
    for v in values:
        if isinstance(v, bool) or v is None:
            continue
        if isinstance(v, (int, float)):
            out.append(float(v))
    return out


def _paired_values(
    baseline_trials: list[dict[str, Any]],
    arm_trials: list[dict[str, Any]],
    key: str,
) -> tuple[list[float], list[float]] | None:
    """Match trials across arms by pairId (preferred) or personaId; numeric only."""
    def index(trials: list[dict[str, Any]]) -> dict[str, float]:
        idx: dict[str, float] = {}
        for t in trials:
            link = t.get("pairId") or t.get("personaId")
            if not link:
                continue
            val = t.get("metrics", {}).get(key)
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                continue
            idx[str(link)] = float(val)
        return idx

    b_idx = index(baseline_trials)
    a_idx = index(arm_trials)
    shared = sorted(set(b_idx) & set(a_idx))
    if len(shared) < 2:
        return None
    return [b_idx[s] for s in shared], [a_idx[s] for s in shared]


# --------------------------------------------------------------------------
# Per-metric comparisons
# --------------------------------------------------------------------------

def _compare_numerical(
    baseline_trials: list[dict[str, Any]],
    arm_trials: list[dict[str, Any]],
    key: str,
    *,
    alpha: float = 0.05,
) -> dict[str, Any]:
    base_all = _numeric(t.get("metrics", {}).get(key) for t in baseline_trials)
    arm_all = _numeric(t.get("metrics", {}).get(key) for t in arm_trials)
    result: dict[str, Any] = {
        "kind": "numerical",
        "scale": _infer_numeric_scale(base_all + arm_all),
        "baseline": _numeric_summary(base_all),
        "treatment": _numeric_summary(arm_all),
    }
    if len(base_all) < 2 or len(arm_all) < 2:
        result.update({"test": "insufficient_data", "pValue": None, "paired": False})
        return result

    base_mean = float(np.mean(base_all))
    paired = _paired_values(baseline_trials, arm_trials, key)
    if paired is not None:
        b, a = paired
        diff = np.array(a) - np.array(b)
        n = len(b)
        sd = float(np.std(diff, ddof=1)) if n > 1 else 0.0
        if sd == 0:
            # constant difference: zero -> no effect (p=1), non-zero -> deterministic shift (p=0)
            p = 1.0 if float(np.mean(diff)) == 0 else 0.0
            result.update({"test": "paired_t", "pValue": p, "paired": True, "n": n})
        else:
            stat, p = stats.ttest_rel(a, b)
            result.update({"test": "paired_t", "statistic": float(stat), "pValue": float(p), "paired": True, "n": n})
        mean_diff = float(np.mean(a) - np.mean(b))
        se = sd / np.sqrt(n) if n > 0 else 0.0
        df = max(n - 1, 1)
        result["effect"] = _effect_with_ci(mean_diff, se, df, base_mean, cohens_d=float(np.mean(diff) / sd) if sd > 0 else 0.0, alpha=alpha)
        return result

    # Welch's unpaired t-test
    na, nb = len(arm_all), len(base_all)
    var_a = float(np.var(arm_all, ddof=1)) if na > 1 else 0.0
    var_b = float(np.var(base_all, ddof=1)) if nb > 1 else 0.0
    if np.std(base_all) == 0 and np.std(arm_all) == 0 and np.mean(base_all) == np.mean(arm_all):
        result.update({"test": "welch_t", "pValue": 1.0, "paired": False})
    else:
        stat, p = stats.ttest_ind(arm_all, base_all, equal_var=False)
        result.update({"test": "welch_t", "statistic": float(stat), "pValue": float(p) if p == p else None, "paired": False})
    mean_diff = float(np.mean(arm_all) - np.mean(base_all))
    se = float(np.sqrt(var_a / na + var_b / nb)) if na > 0 and nb > 0 else 0.0
    df = _welch_df(var_a, na, var_b, nb)
    result["effect"] = _effect_with_ci(mean_diff, se, df, base_mean, cohens_d=_cohens_d(arm_all, base_all), alpha=alpha)
    return result


def _welch_df(var_a: float, na: int, var_b: float, nb: int) -> float:
    if na < 2 or nb < 2:
        return float(max(min(na, nb) - 1, 1))
    num = (var_a / na + var_b / nb) ** 2
    den = (var_a / na) ** 2 / (na - 1) + (var_b / nb) ** 2 / (nb - 1)
    if den == 0:
        return float(na + nb - 2)
    return float(num / den)


def _effect_with_ci(
    mean_diff: float,
    se: float,
    df: float,
    base_mean: float,
    *,
    cohens_d: float,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Effect payload for the scorecard: absolute diff + Cohen's d + a 95% CI on
    the diff, plus percentage-of-baseline deltas for the CI bar chart."""
    if se > 0 and df >= 1:
        tcrit = float(stats.t.ppf(1 - alpha / 2, df))
        margin = tcrit * se
    else:
        margin = 0.0
    lo, hi = mean_diff - margin, mean_diff + margin
    effect: dict[str, Any] = {
        "diff": mean_diff,
        "cohensD": cohens_d,
        "ci": [lo, hi],
    }
    if base_mean not in (0, 0.0):
        effect["deltaPct"] = mean_diff / base_mean * 100.0
        effect["ciPct"] = [lo / base_mean * 100.0, hi / base_mean * 100.0]
    return effect


def _infer_numeric_scale(vals: list[float]) -> str:
    """Coarse display scale for UI — not a hard statistical model choice.

    - ``binary``: 0/1 outcomes → show as rate / percentage points
    - ``score``: small integer range (Likert-like) → mean points
    - ``count``: non-negative integers with a wider span → mean + total
    - ``continuous``: everything else
    """
    if not vals:
        return "continuous"
    uniq = {float(v) for v in vals}
    if uniq <= {0.0, 1.0}:
        return "binary"
    ints = all(float(v).is_integer() for v in vals)
    mn, mx = float(min(vals)), float(max(vals))
    if ints and mn >= 0:
        # Likert / discrete ratings typically live in a small closed range.
        if mx <= 10 and (mx - mn) <= 10:
            return "score"
        if mx > 10:
            return "count"
        return "score"
    return "continuous"


def _numeric_summary(vals: list[float]) -> dict[str, Any]:
    if not vals:
        return {
            "n": 0,
            "mean": None,
            "std": None,
            "min": None,
            "max": None,
            "sum": None,
            "median": None,
        }
    arr = np.array(vals, dtype=float)
    return {
        "n": int(arr.size),
        "mean": float(arr.mean()),
        "std": float(arr.std(ddof=1)) if arr.size > 1 else 0.0,
        "min": float(arr.min()),
        "max": float(arr.max()),
        "sum": float(arr.sum()),
        "median": float(np.median(arr)),
    }


def _cohens_d(a: list[float], b: list[float]) -> float:
    a_arr, b_arr = np.array(a), np.array(b)
    na, nb = a_arr.size, b_arr.size
    if na < 2 or nb < 2:
        return 0.0
    pooled_var = ((na - 1) * a_arr.var(ddof=1) + (nb - 1) * b_arr.var(ddof=1)) / (na + nb - 2)
    pooled_sd = float(np.sqrt(pooled_var))
    if pooled_sd == 0:
        return 0.0
    return float((a_arr.mean() - b_arr.mean()) / pooled_sd)


def _categorical(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    for v in values:
        if v is None:
            continue
        out.append("true" if v is True else "false" if v is False else str(v))
    return out


def _compare_categorical(
    baseline_trials: list[dict[str, Any]],
    arm_trials: list[dict[str, Any]],
    key: str,
) -> dict[str, Any]:
    base_cats = _categorical(t.get("metrics", {}).get(key) for t in baseline_trials)
    arm_cats = _categorical(t.get("metrics", {}).get(key) for t in arm_trials)
    base_counts, arm_counts = Counter(base_cats), Counter(arm_cats)
    categories = sorted(set(base_counts) | set(arm_counts))

    result: dict[str, Any] = {
        "kind": "categorical",
        "categories": categories,
        "baseline": {"n": len(base_cats), "distribution": _proportions(base_counts, categories)},
        "treatment": {"n": len(arm_cats), "distribution": _proportions(arm_counts, categories)},
    }
    # Spell out *why* a categorical comparison can't run so the UI can say more
    # than "insufficient data": too few answers vs. everyone picked one category.
    if len(base_cats) < 2 or len(arm_cats) < 2:
        result.update(
            {"test": "insufficient_data", "pValue": None, "reason": "too_few_responses"}
        )
        return result
    if len(categories) < 2:
        result.update(
            {"test": "insufficient_data", "pValue": None, "reason": "single_category"}
        )
        return result

    table = np.array([[base_counts.get(c, 0) for c in categories], [arm_counts.get(c, 0) for c in categories]])
    # drop all-zero columns (chi2 needs non-empty)
    table = table[:, table.sum(axis=0) > 0]
    if table.shape[1] < 2:
        result.update(
            {"test": "insufficient_data", "pValue": None, "reason": "single_category"}
        )
        return result
    chi2, p, dof, _ = stats.chi2_contingency(table)
    result.update({"test": "chi_square", "statistic": float(chi2), "dof": int(dof), "pValue": float(p)})
    result["effect"] = {"cramersV": _cramers_v(table, chi2)}
    return result


def _proportions(counts: Counter, categories: list[str]) -> dict[str, float]:
    total = sum(counts.values())
    if total == 0:
        return {c: 0.0 for c in categories}
    return {c: counts.get(c, 0) / total for c in categories}


def _cramers_v(table: np.ndarray, chi2: float) -> float:
    n = table.sum()
    if n == 0:
        return 0.0
    k = min(table.shape) - 1
    if k <= 0:
        return 0.0
    return float(np.sqrt(chi2 / (n * k)))


# --------------------------------------------------------------------------
# Benjamini-Hochberg
# --------------------------------------------------------------------------

def benjamini_hochberg(pvalues: list[float], alpha: float = 0.05) -> list[float]:
    """Return BH-adjusted q-values, order-aligned with the input list."""
    m = len(pvalues)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: pvalues[i])
    adj = [0.0] * m
    prev = 1.0
    for rank, idx in enumerate(reversed(order), start=1):
        i = m - rank + 1  # descending rank
        q = min(prev, pvalues[idx] * m / i)
        adj[idx] = q
        prev = q
    return adj


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

def analyze_experiment(
    arms: list[dict[str, Any]],
    metric_contract: dict[str, Any],
    *,
    metric_kinds: dict[str, str] | None = None,
    alpha: float = 0.05,
    multiple_testing: str = "none",
) -> dict[str, Any]:
    """Compare every non-baseline arm to the baseline on the contract metrics.

    ``arms``: ``[{"cellId","arm","baseline",bool,"trials":[{"personaId","pairId",
    "metrics":{key:value}}]}]``.

    ``multiple_testing``: ``"none"`` (default) flags significance from the raw
    p-value; ``"bh"`` applies Benjamini–Hochberg FDR across tested comparisons.
    Adjusted p-values are always attached when tests ran so the UI can show them.
    """
    method = str(multiple_testing or "none").strip().lower()
    if method in {"bh", "benjamini_hochberg", "fdr"}:
        method = "bh"
    else:
        method = "none"

    if not arms:
        return {
            "baselineCell": None,
            "baselineArm": None,
            "comparisons": [],
            "correction": {"method": method if method == "bh" else "none", "alpha": alpha, "count": 0},
        }

    baseline = next((a for a in arms if a.get("baseline")), arms[0])
    baseline_trials = baseline.get("trials") or []
    roles = _roles_for(metric_contract)
    ordered_keys = list(roles.keys())
    kinds = dict(metric_kinds or {})

    comparisons: list[dict[str, Any]] = []
    for arm in arms:
        if arm is baseline:
            continue
        arm_trials = arm.get("trials") or []
        for key in ordered_keys:
            kind = kinds.get(key)
            if kind is None:
                sample = [t.get("metrics", {}).get(key) for t in baseline_trials + arm_trials]
                kind = _infer_kind(sample)
            if kind == "numerical":
                cmp = _compare_numerical(baseline_trials, arm_trials, key, alpha=alpha)
            elif kind == "categorical":
                cmp = _compare_categorical(baseline_trials, arm_trials, key)
            else:
                cmp = {"kind": "textual", "test": "skipped", "pValue": None}
            cmp.update({
                "cellId": arm.get("cellId"),
                "arm": arm.get("arm"),
                "metricKey": key,
                "role": roles.get(key, "secondary"),
            })
            comparisons.append(cmp)

    tested = [c for c in comparisons if isinstance(c.get("pValue"), (int, float))]
    adj = benjamini_hochberg([float(c["pValue"]) for c in tested], alpha=alpha)
    for c, q in zip(tested, adj):
        c["pValueAdj"] = q
        raw_p = float(c["pValue"])
        c["significant"] = (q <= alpha) if method == "bh" else (raw_p <= alpha)
    for c in comparisons:
        if "significant" not in c:
            c["pValueAdj"] = None
            c["significant"] = False

    return {
        "baselineCell": baseline.get("cellId"),
        "baselineArm": baseline.get("arm") or baseline.get("cellId"),
        "comparisons": comparisons,
        "correction": {
            "method": "benjamini_hochberg" if method == "bh" else "none",
            "alpha": alpha,
            "count": len(tested),
        },
    }


# --------------------------------------------------------------------------
# Persona slices (heterogeneous effects)
# --------------------------------------------------------------------------

# Prefer these when auto-picking a slice dimension (first present wins).
PREFERRED_SLICE_DIMS = (
    "urbanicity",
    "trust_level",
    "economic_motivation",
    "time_pressure",
    "domain_characteristics",
    "values_priority",
    "age_bracket",
    "life_stage",
    "gender",
    "region",
    "income_bracket",
    "education",
)

# Skip ultra-sparse trait ordinals that rarely differentiate cohorts.
_SLICE_DIM_SKIP_PREFIXES = ("trait_", "schwartz_value_", "sdt_need_")


def discover_sliceable_dimensions(
    arms: list[dict[str, Any]],
    *,
    min_distinct: int = 2,
    max_distinct: int = 12,
    min_coverage: float = 0.5,
) -> list[dict[str, Any]]:
    """Scan trial ``dimensions`` maps and return dims suitable for slicing."""
    trials = [t for a in arms for t in (a.get("trials") or [])]
    total = len(trials)
    if total == 0:
        return []

    value_sets: dict[str, set[str]] = {}
    present: dict[str, int] = {}
    for t in trials:
        dims = t.get("dimensions") or {}
        if not isinstance(dims, dict):
            continue
        for key, raw in dims.items():
            if raw is None or raw == "":
                continue
            kid = str(key)
            if any(kid.startswith(p) for p in _SLICE_DIM_SKIP_PREFIXES):
                continue
            present[kid] = present.get(kid, 0) + 1
            value_sets.setdefault(kid, set()).add(str(raw))

    out: list[dict[str, Any]] = []
    for kid, values in value_sets.items():
        cov = present.get(kid, 0) / total
        n_distinct = len(values)
        if n_distinct < min_distinct or n_distinct > max_distinct or cov < min_coverage:
            continue
        out.append(
            {
                "id": kid,
                "distinctValues": n_distinct,
                "coverage": round(cov, 3),
                "values": sorted(values),
            }
        )

    pref = {d: i for i, d in enumerate(PREFERRED_SLICE_DIMS)}
    out.sort(key=lambda row: (pref.get(row["id"], 10_000), -row["coverage"], row["id"]))
    return out


def _filter_trials_by_dim(
    trials: list[dict[str, Any]],
    dimension: str,
    value: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for t in trials:
        dims = t.get("dimensions") or {}
        if not isinstance(dims, dict):
            continue
        if str(dims.get(dimension, "")) == value:
            out.append(t)
    return out


def analyze_persona_slices(
    arms: list[dict[str, Any]],
    metric_contract: dict[str, Any],
    *,
    dimension: str,
    metric_key: str,
    metric_kinds: dict[str, str] | None = None,
    alpha: float = 0.05,
    min_n: int = 3,
    include_guardrails: bool = True,
) -> dict[str, Any]:
    """Per-dimension-value lift for ``metric_key``, plus compact guardrail diffs."""
    if not arms or not dimension or not metric_key:
        return {
            "dimension": dimension,
            "metricKey": metric_key,
            "rows": [],
            "skipped": [],
        }

    baseline = next((a for a in arms if a.get("baseline")), arms[0])
    baseline_trials = baseline.get("trials") or []
    kinds = dict(metric_kinds or {})
    roles = _roles_for(metric_contract)
    guardrail_keys = (
        [k for k, role in roles.items() if role == "guardrail"] if include_guardrails else []
    )

    # Values present on either arm for this dimension.
    values: set[str] = set()
    for a in arms:
        for t in a.get("trials") or []:
            dims = t.get("dimensions") or {}
            if isinstance(dims, dict) and dims.get(dimension) not in (None, ""):
                values.add(str(dims[dimension]))

    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for arm in arms:
        if arm is baseline:
            continue
        arm_trials = arm.get("trials") or []
        for value in sorted(values):
            b_slice = _filter_trials_by_dim(baseline_trials, dimension, value)
            a_slice = _filter_trials_by_dim(arm_trials, dimension, value)
            if len(b_slice) < min_n or len(a_slice) < min_n:
                skipped.append(
                    {
                        "value": value,
                        "cellId": arm.get("cellId"),
                        "arm": arm.get("arm"),
                        "nBaseline": len(b_slice),
                        "nTreatment": len(a_slice),
                        "reason": "insufficient_n",
                    }
                )
                continue

            kind = kinds.get(metric_key)
            if kind is None:
                sample = [t.get("metrics", {}).get(metric_key) for t in b_slice + a_slice]
                kind = _infer_kind(sample)
            if kind == "numerical":
                cmp = _compare_numerical(b_slice, a_slice, metric_key, alpha=alpha)
            elif kind == "categorical":
                cmp = _compare_categorical(b_slice, a_slice, metric_key)
            else:
                skipped.append(
                    {
                        "value": value,
                        "cellId": arm.get("cellId"),
                        "arm": arm.get("arm"),
                        "nBaseline": len(b_slice),
                        "nTreatment": len(a_slice),
                        "reason": "unsupported_kind",
                    }
                )
                continue

            raw_p = cmp.get("pValue")
            significant = isinstance(raw_p, (int, float)) and float(raw_p) <= alpha

            guardrails: list[dict[str, Any]] = []
            for gk in guardrail_keys:
                g_kind = kinds.get(gk)
                if g_kind is None:
                    sample = [t.get("metrics", {}).get(gk) for t in b_slice + a_slice]
                    g_kind = _infer_kind(sample)
                if g_kind != "numerical":
                    continue
                g_cmp = _compare_numerical(b_slice, a_slice, gk, alpha=alpha)
                g_diff = (g_cmp.get("effect") or {}).get("diff")
                g_p = g_cmp.get("pValue")
                guardrails.append(
                    {
                        "metricKey": gk,
                        "diff": g_diff,
                        "deltaPct": (g_cmp.get("effect") or {}).get("deltaPct"),
                        "pValue": g_p,
                        "significant": isinstance(g_p, (int, float)) and float(g_p) <= alpha,
                        "scale": g_cmp.get("scale"),
                    }
                )

            rows.append(
                {
                    "value": value,
                    "cellId": arm.get("cellId"),
                    "arm": arm.get("arm"),
                    "metricKey": metric_key,
                    "role": roles.get(metric_key, "secondary"),
                    "kind": cmp.get("kind"),
                    "scale": cmp.get("scale"),
                    "test": cmp.get("test"),
                    "paired": cmp.get("paired"),
                    "nBaseline": len(b_slice),
                    "nTreatment": len(a_slice),
                    "pValue": raw_p,
                    "significant": significant,
                    "effect": cmp.get("effect"),
                    "baseline": cmp.get("baseline"),
                    "treatment": cmp.get("treatment"),
                    "categories": cmp.get("categories"),
                    "guardrails": guardrails,
                }
            )

    return {
        "dimension": dimension,
        "metricKey": metric_key,
        "rows": rows,
        "skipped": skipped,
    }


def rank_persona_drivers(
    arms: list[dict[str, Any]],
    metric_contract: dict[str, Any],
    *,
    metric_key: str,
    candidate_dimensions: list[str],
    metric_kinds: dict[str, str] | None = None,
    alpha: float = 0.05,
    min_n: int = 3,
    max_scan: int = 16,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Auto-rank attributes by uneven treatment effect across persona values.

    A/B/n: ranks **per treatment arm** (each driver carries ``cellId`` / ``arm``),
    then keeps up to ``top_k`` drivers for each arm. Score = max−min segment lift.
    """
    if not arms or not metric_key or not candidate_dimensions:
        return []

    kinds = dict(metric_kinds or {})
    kind = kinds.get(metric_key)
    if kind is None:
        sample = [
            t.get("metrics", {}).get(metric_key)
            for a in arms
            for t in (a.get("trials") or [])
        ]
        kind = _infer_kind(sample)
    if kind != "numerical":
        # Categorical overall association doesn't decompose cleanly into “who
        # drove the lift” — skip auto-drivers for now.
        return []

    # cellId → list of driver candidates for that treatment arm
    per_arm: dict[str, list[dict[str, Any]]] = {}

    for dimension in candidate_dimensions[:max_scan]:
        sliced = analyze_persona_slices(
            arms,
            metric_contract,
            dimension=dimension,
            metric_key=metric_key,
            metric_kinds=kinds,
            alpha=alpha,
            min_n=min_n,
            include_guardrails=False,
        )
        by_arm: dict[str, list[dict[str, Any]]] = {}
        for row in sliced.get("rows") or []:
            if row.get("kind") != "numerical":
                continue
            if not isinstance((row.get("effect") or {}).get("diff"), (int, float)):
                continue
            cid = str(row.get("cellId") or "")
            by_arm.setdefault(cid, []).append(row)

        for cid, rows in by_arm.items():
            if len(rows) < 2:
                continue
            diffs = [float(r["effect"]["diff"]) for r in rows]
            spread = max(diffs) - min(diffs)
            if spread <= 0:
                continue
            best = max(rows, key=lambda r: float(r["effect"]["diff"]))
            worst = min(rows, key=lambda r: float(r["effect"]["diff"]))
            per_arm.setdefault(cid, []).append(
                {
                    "dimension": dimension,
                    "metricKey": metric_key,
                    "cellId": best.get("cellId") or cid,
                    "arm": best.get("arm"),
                    "spread": spread,
                    "scale": best.get("scale"),
                    "segmentCount": len(rows),
                    "highest": {
                        "value": best.get("value"),
                        "diff": float(best["effect"]["diff"]),
                        "deltaPct": (best.get("effect") or {}).get("deltaPct"),
                        "nBaseline": best.get("nBaseline"),
                        "nTreatment": best.get("nTreatment"),
                        "pValue": best.get("pValue"),
                        "significant": bool(best.get("significant")),
                    },
                    "lowest": {
                        "value": worst.get("value"),
                        "diff": float(worst["effect"]["diff"]),
                        "deltaPct": (worst.get("effect") or {}).get("deltaPct"),
                        "nBaseline": worst.get("nBaseline"),
                        "nTreatment": worst.get("nTreatment"),
                        "pValue": worst.get("pValue"),
                        "significant": bool(worst.get("significant")),
                    },
                }
            )

    out: list[dict[str, Any]] = []
    for cid in sorted(per_arm.keys()):
        ranked = sorted(
            per_arm[cid],
            key=lambda d: (-float(d["spread"]), d["dimension"]),
        )[:top_k]
        out.extend(ranked)
    return out


def paired_persona_deltas(
    arms: list[dict[str, Any]],
    metric_key: str,
    *,
    limit: int = 25,
) -> dict[str, Any] | None:
    """Per-persona treatment−control diffs when arms share pairId/personaId."""
    if not arms or not metric_key:
        return None
    baseline = next((a for a in arms if a.get("baseline")), arms[0])
    treat = next((a for a in arms if a is not baseline), None)
    if treat is None:
        return None

    def index(trials: list[dict[str, Any]]) -> dict[str, tuple[str, float]]:
        idx: dict[str, tuple[str, float]] = {}
        for t in trials:
            link = t.get("pairId") or t.get("personaId")
            if not link:
                continue
            val = t.get("metrics", {}).get(metric_key)
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                continue
            pid = str(t.get("personaId") or link)
            idx[str(link)] = (pid, float(val))
        return idx

    b_idx = index(baseline.get("trials") or [])
    a_idx = index(treat.get("trials") or [])
    shared = sorted(set(b_idx) & set(a_idx))
    if len(shared) < 2:
        return {
            "metricKey": metric_key,
            "cellId": treat.get("cellId"),
            "arm": treat.get("arm"),
            "paired": False,
            "worse": [],
            "better": [],
            "unchanged": 0,
            "n": 0,
        }

    rows: list[dict[str, Any]] = []
    unchanged = 0
    for link in shared:
        pid_b, bv = b_idx[link]
        pid_a, av = a_idx[link]
        diff = av - bv
        if abs(diff) < 1e-12:
            unchanged += 1
            continue
        rows.append(
            {
                "personaId": pid_a or pid_b,
                "pairId": link,
                "control": bv,
                "treatment": av,
                "diff": diff,
            }
        )

    worse = sorted([r for r in rows if r["diff"] < 0], key=lambda r: r["diff"])[:limit]
    better = sorted([r for r in rows if r["diff"] > 0], key=lambda r: -r["diff"])[:limit]
    return {
        "metricKey": metric_key,
        "cellId": treat.get("cellId"),
        "arm": treat.get("arm"),
        "paired": True,
        "worse": worse,
        "better": better,
        "unchanged": unchanged,
        "n": len(shared),
    }
