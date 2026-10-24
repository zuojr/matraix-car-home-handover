"""Experiment design expansion (pure, dependency-free).

Given a task's factors (from ``experiment.json``) and a chosen design, expand the
factor space into concrete experiment **cells** (arms). Each cell fixes one level
per participating factor and carries the merged stimulus ``params`` that the
orchestration layer injects into that arm's trials (as ``MATRIX_PARAM_*``).

Contract shape (explicit split, canonical):

- ``factors[]`` — variables that VARY. Only ``space == "system"`` factors expand
  into cells; ``space == "persona"`` factors are the persona-attribute contrast
  (the PUT dimension) and are surfaced separately, not injected as stimulus.
- ``constants[]`` — variables PINNED to one value across every cell. Merged into
  each cell's ``params`` (so they ride as ``MATRIX_PARAM_*`` too).

Each level's stimulus value may be given as ``value`` (single value keyed by the
factor id) or as ``params`` (multi-key). The factor's control level is named by
``baseline`` (a level id); legacy per-level ``baseline: true`` is still honored.

Designs:

- ``full_factorial`` — cartesian product of all selected factors' levels.
- ``ab_n`` — one-factor-at-a-time (OFAT): the all-baseline cell, plus one cell per
  non-baseline level of each factor. Arms = 1 + Σ(levels_i − 1).
- ``fractional`` — 2-level orthogonal array (Taguchi L4/L8/L16). Only valid when
  every selected factor has exactly two levels and the factor count fits an
  array; otherwise falls back to ``full_factorial`` (reported via
  ``effectiveType``).

No third-party dependencies so it stays trivially testable.
"""

from __future__ import annotations

from itertools import product
from typing import Any


# --------------------------------------------------------------------------
# Factor normalization
# --------------------------------------------------------------------------

def _baseline_index(factor: dict[str, Any], levels: list[dict[str, Any]]) -> int:
    """Control level index. Prefer factor-level ``baseline`` (a level id); fall
    back to a legacy per-level ``baseline: true``; else the first level."""
    baseline_id = factor.get("baseline")
    if isinstance(baseline_id, str) and baseline_id:
        for i, lvl in enumerate(levels):
            if lvl.get("id") == baseline_id:
                return i
    for i, lvl in enumerate(levels):
        if lvl.get("baseline") is True:
            return i
    return 0


def _level_params(factor_id: str, level: dict[str, Any]) -> dict[str, Any]:
    """Stimulus params for a level: explicit ``params`` win; otherwise the single
    ``value`` is keyed by the factor id."""
    params = dict(level.get("params") or {})
    if not params and level.get("value") is not None:
        params[factor_id] = level["value"]
    return params


def is_persona_space(factor: dict[str, Any]) -> bool:
    return str(factor.get("space") or "system").lower() == "persona"


def normalize_factors(
    factors: list[dict[str, Any]],
    *,
    selected: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Validate + subset the **system-space** factors that expand into cells.

    ``space == "persona"`` factors are excluded here (they are the persona
    contrast, surfaced via :func:`persona_factors`, not stimulus cells).
    ``selected`` (factor ids) filters and orders participating factors; when
    omitted, all system factors participate in their declared order.
    """
    by_id = {f["id"]: f for f in factors if isinstance(f, dict) and f.get("id")}
    if selected:
        order = list(selected)
    else:
        order = [f["id"] for f in factors if f.get("id") and not is_persona_space(f)]
    out: list[dict[str, Any]] = []
    for fid in order:
        factor = by_id.get(fid)
        if factor is None:
            raise ValueError(f"Unknown factor id: {fid!r}")
        if is_persona_space(factor):
            # A persona-space factor is the contrast dimension, never a cell axis.
            continue
        levels = [lvl for lvl in (factor.get("levels") or []) if isinstance(lvl, dict) and lvl.get("id")]
        if not levels:
            raise ValueError(f"Factor {fid!r} has no levels")
        out.append(
            {
                "id": fid,
                "label": factor.get("label") or fid,
                "levels": [
                    {
                        "id": lvl["id"],
                        "label": lvl.get("label") or lvl["id"],
                        "baseline": _baseline_index(factor, levels) == i,
                        "params": _level_params(fid, lvl),
                    }
                    for i, lvl in enumerate(levels)
                ],
                "baselineIndex": _baseline_index(factor, levels),
            }
        )
    return out


def persona_factors(factors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the ``space == "persona"`` factors (the persona contrast dimension).

    Its levels are the candidate arms for a PUT (compareBy=persona) design; the
    baseline level names the control arm.
    """
    out: list[dict[str, Any]] = []
    for factor in factors:
        if not isinstance(factor, dict) or not factor.get("id") or not is_persona_space(factor):
            continue
        levels = [lvl for lvl in (factor.get("levels") or []) if isinstance(lvl, dict) and lvl.get("id")]
        baseline_idx = _baseline_index(factor, levels) if levels else 0
        out.append(
            {
                "id": factor["id"],
                "label": factor.get("label") or factor["id"],
                "source": str(factor.get("source") or "catalog"),
                "levels": [
                    {
                        "id": lvl["id"],
                        "label": lvl.get("label") or lvl["id"],
                        "value": lvl.get("value", lvl.get("label") or lvl["id"]),
                        "baseline": baseline_idx == i,
                    }
                    for i, lvl in enumerate(levels)
                ],
            }
        )
    return out


def constants_params(constants: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Flatten ``constants[]`` into a ``{id: value}`` map (pinned across cells)."""
    out: dict[str, Any] = {}
    for const in constants or []:
        if not isinstance(const, dict):
            continue
        cid = const.get("id")
        if not cid or const.get("value") is None:
            continue
        out[str(cid)] = const["value"]
    return out


# --------------------------------------------------------------------------
# Cell construction
# --------------------------------------------------------------------------

def _cell(factors: list[dict[str, Any]], level_indices: list[int]) -> dict[str, Any]:
    factor_levels: dict[str, str] = {}
    params: dict[str, Any] = {}
    arm_bits: list[str] = []
    is_baseline = True
    for factor, idx in zip(factors, level_indices):
        level = factor["levels"][idx]
        factor_levels[factor["id"]] = level["id"]
        params.update(level["params"])
        arm_bits.append(f"{factor['label']}={level['label']}")
        if idx != factor["baselineIndex"]:
            is_baseline = False
    cell_id = ";".join(f"{fid}={lid}" for fid, lid in sorted(factor_levels.items()))
    return {
        "cellId": cell_id,
        "arm": " · ".join(arm_bits),
        "baseline": is_baseline,
        "factorLevels": factor_levels,
        "params": params,
    }


def _full_factorial(factors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranges = [range(len(f["levels"])) for f in factors]
    return [_cell(factors, list(combo)) for combo in product(*ranges)]


def _ab_n(factors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    baseline_idx = [f["baselineIndex"] for f in factors]
    cells = [_cell(factors, list(baseline_idx))]
    for fi, factor in enumerate(factors):
        for li in range(len(factor["levels"])):
            if li == factor["baselineIndex"]:
                continue
            indices = list(baseline_idx)
            indices[fi] = li
            cells.append(_cell(factors, indices))
    return cells


# Taguchi 2-level orthogonal arrays. Rows are runs, columns are factors (0/1).
# Column 0 is the baseline level index, 1 the alternative.
_OA_2LEVEL: dict[int, list[list[int]]] = {
    # L4: up to 3 factors, 4 runs
    3: [
        [0, 0, 0],
        [0, 1, 1],
        [1, 0, 1],
        [1, 1, 0],
    ],
    # L8: up to 7 factors, 8 runs
    7: [
        [0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 1, 1, 1, 1],
        [0, 1, 1, 0, 0, 1, 1],
        [0, 1, 1, 1, 1, 0, 0],
        [1, 0, 1, 0, 1, 0, 1],
        [1, 0, 1, 1, 0, 1, 0],
        [1, 1, 0, 0, 1, 1, 0],
        [1, 1, 0, 1, 0, 0, 1],
    ],
    # L16: up to 15 factors, 16 runs
    15: [
        [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1],
        [0, 0, 0, 1, 1, 1, 1, 0, 0, 0, 0, 1, 1, 1, 1],
        [0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0],
        [0, 1, 1, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 1, 1],
        [0, 1, 1, 0, 0, 1, 1, 1, 1, 0, 0, 1, 1, 0, 0],
        [0, 1, 1, 1, 1, 0, 0, 0, 0, 1, 1, 1, 1, 0, 0],
        [0, 1, 1, 1, 1, 0, 0, 1, 1, 0, 0, 0, 0, 1, 1],
        [1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1],
        [1, 0, 1, 0, 1, 0, 1, 1, 0, 1, 0, 1, 0, 1, 0],
        [1, 0, 1, 1, 0, 1, 0, 0, 1, 0, 1, 1, 0, 1, 0],
        [1, 0, 1, 1, 0, 1, 0, 1, 0, 1, 0, 0, 1, 0, 1],
        [1, 1, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 1, 1, 0],
        [1, 1, 0, 0, 1, 1, 0, 1, 0, 0, 1, 1, 0, 0, 1],
        [1, 1, 0, 1, 0, 0, 1, 0, 1, 1, 0, 1, 0, 0, 1],
        [1, 1, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0, 1, 1, 0],
    ],
}


def _select_orthogonal_array(n_factors: int) -> list[list[int]] | None:
    for capacity in sorted(_OA_2LEVEL):
        if n_factors <= capacity:
            return _OA_2LEVEL[capacity]
    return None


def _fractional(factors: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    """Return (cells, effectiveType). Falls back to full_factorial when no OA fits."""
    if any(len(f["levels"]) != 2 for f in factors):
        return _full_factorial(factors), "full_factorial"
    array = _select_orthogonal_array(len(factors))
    if array is None:
        return _full_factorial(factors), "full_factorial"

    # Map array column 0/1 -> baseline / non-baseline level index per factor.
    def level_index(factor: dict[str, Any], bit: int) -> int:
        base = factor["baselineIndex"]
        if bit == 0:
            return base
        return 1 - base  # the other of the two levels

    seen: set[str] = set()
    cells: list[dict[str, Any]] = []
    for run in array:
        indices = [level_index(f, run[i]) for i, f in enumerate(factors)]
        cell = _cell(factors, indices)
        if cell["cellId"] in seen:
            continue
        seen.add(cell["cellId"])
        cells.append(cell)
    return cells, "fractional"


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

def expand_design(
    factors: list[dict[str, Any]],
    *,
    design_type: str = "full_factorial",
    selected_factors: list[str] | None = None,
    constants: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Expand a factor space into experiment cells.

    Only ``space == "system"`` factors form cells; ``constants[]`` are pinned into
    every cell's ``params``. When there are no system factors (a compareBy=persona
    task whose environment is entirely in ``constants``), a single all-baseline
    cell carrying just the constants is returned.

    Returns ``{"type", "effectiveType", "factors", "personaFactors", "cells"}``
    where exactly one cell has ``baseline: true`` (the all-baseline arm).
    """
    norm = normalize_factors(factors, selected=selected_factors)
    pinned = constants_params(constants)

    if not norm:
        # No varying system factor: the "environment" is the pinned constants.
        cells = [
            {
                "cellId": "baseline",
                "arm": "",
                "baseline": True,
                "factorLevels": {},
                "params": dict(pinned),
            }
        ]
        effective = design_type
    else:
        if design_type == "full_factorial":
            cells, effective = _full_factorial(norm), "full_factorial"
        elif design_type == "ab_n":
            cells, effective = _ab_n(norm), "ab_n"
        elif design_type == "fractional":
            cells, effective = _fractional(norm)
        else:
            raise ValueError(f"Unknown design_type: {design_type!r}")
        if pinned:
            for cell in cells:
                cell["params"] = {**pinned, **(cell.get("params") or {})}

    return {
        "type": design_type,
        "effectiveType": effective,
        "factors": [
            {
                "id": f["id"],
                "label": f["label"],
                "levels": [
                    {"id": level["id"], "label": level["label"], "baseline": level["baseline"]}
                    for level in f["levels"]
                ],
            }
            for f in norm
        ],
        "personaFactors": persona_factors(factors),
        "constants": pinned,
        "cells": cells,
    }
