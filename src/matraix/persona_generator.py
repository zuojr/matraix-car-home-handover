"""Sample synthetic persona YAML from the Full DAG."""

from __future__ import annotations

import itertools
import json
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import yaml

from matraix.persona_consistency import (
    CONSTRAINED_DIMENSIONS,
    load_dev_dimension_ids,
    load_dev_dimension_index_order,
    allowed_age_brackets_for_life_stage,
    allowed_education,
    allowed_life_stages,
    allowed_seniorities,
    allowed_years_experience,
    validate_dimensions,
)

if TYPE_CHECKING:
    from persona.synthesis.sampler import PersonaForwardSampler

DEFAULT_CATALOG_PATH = "persona/schema/dimensions.json"
DEFAULT_PERSONA_VERSION = "1.0"
SYNTHETIC_SOURCE = "synthetic"
OVERLAY_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
GENERATE_COUNT_DEFAULT = 2000
GENERATE_COUNT_MAX = 5000
MAX_FILTER_STRATA = 2048


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_catalog_values(
    catalog_path: str | Path | None = None,
) -> dict[str, list[str]]:
    path = Path(catalog_path or DEFAULT_CATALOG_PATH)
    if not path.is_file():
        path = _repo_root() / str(catalog_path or DEFAULT_CATALOG_PATH)
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, list[str]] = {}
    for row in payload.get("dimensions") or []:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        dim_id = str(row["id"])
        out[dim_id] = [str(v) for v in row.get("values") or []]
    return out


def _pick(rng, values: list[str]) -> str:
    if not values:
        raise ValueError("empty value list")
    return rng.choice(values)


def _sort_dimensions(
    dimensions: dict[str, str], *, catalog_path: str
) -> dict[str, str]:
    order = load_dev_dimension_index_order(catalog_path=catalog_path)
    return dict(
        sorted(
            dimensions.items(),
            key=lambda item: (order.get(item[0], 99999), item[0]),
        )
    )


def generate_persona_dimensions(
    *,
    rng,
    catalog: dict[str, list[str]],
    dev_dimension_ids: tuple[str, ...],
    catalog_path: str = DEFAULT_CATALOG_PATH,
    age_bracket: str | None = None,
    fixed_dimensions: dict[str, str] | None = None,
) -> dict[str, str]:
    """Sample one internally consistent dimension assignment."""
    fixed = dict(fixed_dimensions or {})
    if fixed.get("age_bracket"):
        age = fixed["age_bracket"]
    elif age_bracket:
        age = age_bracket
    elif fixed.get("life_stage"):
        # Fixed life_stage without age: pick a compatible bracket first so
        # seniority / education lists are never empty (e.g. Student + 65+).
        age = _pick(rng, allowed_age_brackets_for_life_stage(fixed["life_stage"]))
    else:
        age = _pick(rng, catalog["age_bracket"])

    life = fixed.get("life_stage") or _pick(rng, allowed_life_stages(age))
    seniority = fixed.get("seniority") or _pick(
        rng, allowed_seniorities(life_stage=life, age_bracket=age)
    )
    years = fixed.get("years_experience") or _pick(
        rng, allowed_years_experience(age_bracket=age, seniority=seniority)
    )
    education = fixed.get("highest_education") or _pick(
        rng, allowed_education(age_bracket=age, life_stage=life)
    )

    dimensions: dict[str, str] = {
        "age_bracket": age,
        "life_stage": life,
        "seniority": seniority,
        "years_experience": years,
        "highest_education": education,
    }

    for dim_id in dev_dimension_ids:
        if dim_id in CONSTRAINED_DIMENSIONS:
            continue
        if dim_id in fixed:
            dimensions[dim_id] = fixed[dim_id]
            continue
        if dim_id not in catalog:
            raise KeyError(f"Missing dimension {dim_id!r} in catalog")
        dimensions[dim_id] = _pick(rng, catalog[dim_id])

    dimensions = _sort_dimensions(dimensions, catalog_path=catalog_path)

    errors = validate_dimensions(dimensions)
    if errors:
        raise RuntimeError(f"Generated counterfactual persona: {errors}")
    return dimensions


def _stratum_match(dimensions: dict[str, str], stratum: dict[str, str]) -> bool:
    return all(dimensions.get(key) == value for key, value in stratum.items())


def _count_stratum(personas: list[dict[str, Any]], stratum: dict[str, str]) -> int:
    return sum(1 for entry in personas if _stratum_match(entry["dimensions"], stratum))


def _persona_entry(
    *,
    persona_id: str,
    dimensions: dict[str, str],
    version: str,
) -> dict[str, Any]:
    return {
        "persona_id": persona_id,
        "version": version,
        "source": SYNTHETIC_SOURCE,
        "dimensions": dimensions,
    }


def _dag_sampler(*, seed: int) -> PersonaForwardSampler:
    root = str(_repo_root())
    if root not in sys.path:
        sys.path.insert(0, root)
    from persona.synthesis.sampler import DEFAULT_GRAPH_PATH, PersonaForwardSampler, SamplingConfig

    return PersonaForwardSampler(DEFAULT_GRAPH_PATH, SamplingConfig(seed=seed))


def supported_extra_assignments(
    cell: dict[str, str],
    extra_filters: dict[str, list[str]],
    *,
    sampler: PersonaForwardSampler,
    max_tries: int = 2048,
) -> list[dict[str, str]]:
    """DAG-supported assignments of non-stratify filter dims for one cell.

    An empty ``extra_filters`` yields a single empty assignment (stratify pins only).
    """
    if not extra_filters:
        return [{}]
    extra_dims = sorted(extra_filters)
    extra_values = [list(extra_filters[dim]) for dim in extra_dims]
    found: list[dict[str, str]] = []
    for index, combo in enumerate(itertools.product(*extra_values)):
        if index >= max_tries:
            break
        pinned = dict(zip(extra_dims, combo, strict=True))
        if sampler.assignment_supported({**cell, **pinned}):
            found.append(pinned)
    return found


def top_up_strata(
    personas: list[dict[str, Any]],
    *,
    strata: list[dict[str, str]],
    min_per_stratum: int,
    persona_version: str = DEFAULT_PERSONA_VERSION,
    sampler: PersonaForwardSampler | None = None,
    seed: int = 42,
    extra_filters: dict[str, list[str]] | None = None,
    cell_quotas: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Add synthetic rows until each filter cell reaches its quota.

    ``cell_quotas`` (same length as ``strata``) overrides ``min_per_stratum``.
    Stratify keys are pinned on every row. Extra filter dims are drawn
    uniformly from DAG-supported combinations per person when present.
    """
    if cell_quotas is not None and len(cell_quotas) != len(strata):
        raise ValueError("cell_quotas must align with strata")
    if cell_quotas is None and min_per_stratum < 1:
        return personas

    out = list(personas)
    next_index = max((int(entry["persona_id"]) for entry in out), default=0) + 1
    dag = sampler or _dag_sampler(seed=seed)
    extras = extra_filters or {}
    rng = random.Random(seed)

    for index, stratum in enumerate(strata):
        target = cell_quotas[index] if cell_quotas is not None else min_per_stratum
        if target < 1:
            continue
        if not dag.assignment_supported(stratum):
            continue
        assignments = supported_extra_assignments(stratum, extras, sampler=dag)
        if not assignments:
            continue
        need = target - _count_stratum(out, stratum)
        if need <= 0:
            continue
        for _ in range(need):
            extra_pin = rng.choice(assignments)
            for row in dag.sample(1, fixed={**stratum, **extra_pin}):
                out.append(
                    _persona_entry(
                        persona_id=str(next_index).zfill(4),
                        dimensions=dict(row),
                        version=persona_version,
                    )
                )
                next_index += 1
    return out


def build_probe_strata(
    *,
    confounders: dict[str, str],
    probe_dimension: str,
    probe_values: list[str],
) -> list[dict[str, str]]:
    """One fixed combo per probe value (confounders + probe)."""
    probe_key = probe_dimension.removeprefix("dimensions.")
    return [{**confounders, probe_key: value} for value in probe_values]


def build_filter_strata(
    dimension_filters: dict[str, list[str]],
    *,
    max_strata: int = 2048,
) -> list[dict[str, str]]:
    """Cartesian product of multi-value ``dimensionFilters`` → one cell per combination.

    Pass the result through ``filter_strata_on_dag`` before pinning cells on the
    Full DAG. ``filter_feasible_strata`` is a catalog check for existing pools.
    """
    if not dimension_filters:
        return []

    dims = sorted(
        (
            (
                str(dim).removeprefix("dimensions.").strip(),
                [str(v).strip() for v in values if str(v).strip()],
            )
            for dim, values in dimension_filters.items()
        ),
        key=lambda item: item[0],
    )
    dims = [(dim, values) for dim, values in dims if dim and values]
    if not dims:
        return []

    strata: list[dict[str, str]] = [{}]
    for dim, values in dims:
        next_strata: list[dict[str, str]] = []
        for cell in strata:
            for value in values:
                next_strata.append({**cell, dim: value})
                if len(next_strata) > max_strata:
                    raise ValueError(
                        f"dimensionFilters expand to more than {max_strata} strata; "
                        "narrow filters or raise max_strata"
                    )
        strata = next_strata
    return strata


def filter_feasible_strata(
    strata: list[dict[str, str]],
    *,
    catalog_path: str | Path | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Drop filter cells that combine incompatible constrained dimensions.

    Returns ``(kept, dropped)``.
    """
    cat_path = str(catalog_path or DEFAULT_CATALOG_PATH)
    catalog = load_catalog_values(cat_path)
    dev_ids = load_dev_dimension_ids(catalog_path=cat_path)
    rng = random.Random(0)
    feasible: list[dict[str, str]] = []
    dropped: list[dict[str, str]] = []
    for stratum in strata:
        try:
            generate_persona_dimensions(
                rng=rng,
                catalog=catalog,
                dev_dimension_ids=dev_ids,
                catalog_path=cat_path,
                age_bracket=stratum.get("age_bracket"),
                fixed_dimensions=stratum,
            )
        except (RuntimeError, ValueError):
            dropped.append(stratum)
            continue
        feasible.append(stratum)
    return feasible, dropped


def filter_strata_on_dag(
    strata: list[dict[str, str]],
    *,
    sampler: PersonaForwardSampler | None = None,
    seed: int = 42,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Keep filter cells the Full DAG can pin.

    Drops unknown dimension/value pairs and cells that hit a DAG hard mask.
    Returns ``(kept, dropped)``.
    """
    dag = sampler or _dag_sampler(seed=seed)
    kept: list[dict[str, str]] = []
    dropped: list[dict[str, str]] = []
    for stratum in strata:
        if dag.assignment_supported(stratum):
            kept.append(stratum)
        else:
            dropped.append(stratum)
    return kept, dropped


def stratified_cell_quota(
    *,
    allocation: str | None,
    per_cell: int | None,
    sample_size: int | None,
    n_cells: int,
    default: int = 2,
) -> int:
    """Rows per stratify cell so a later Playground draw will not run short.

    Matches Playground stratified sampling:

    * ``perCell`` — ``N`` in every cell (cohort = ``N × #cells``)
    * ``equalTotal`` — ``ceil(sampleSize / #cells)`` then the draw clips to ``sampleSize``
    * ``proportional`` — same floor so every cell exists and the pool is ≥ ``sampleSize``
    """
    if n_cells < 1:
        raise ValueError("n_cells must be >= 1")
    alloc = str(allocation or "").strip()
    if alloc == "perCell":
        if not isinstance(per_cell, int) or per_cell < 1:
            raise ValueError('allocation "perCell" requires perCell >= 1')
        return per_cell
    if alloc in {"equalTotal", "proportional"}:
        if not isinstance(sample_size, int) or sample_size < 1:
            raise ValueError(f'allocation "{alloc}" requires sampleSize >= 1')
        if alloc == "equalTotal" and sample_size < n_cells:
            raise ValueError(
                f"sampleSize={sample_size} is below the stratified cell count={n_cells} "
                "(need ≥1 persona per combination)"
            )
        return max(1, (sample_size + n_cells - 1) // n_cells)
    if isinstance(per_cell, int) and per_cell >= 1:
        return per_cell
    if isinstance(sample_size, int) and sample_size >= 1:
        return max(1, (sample_size + n_cells - 1) // n_cells)
    return default


def hamilton_allocate_weights(
    weights: dict[str, float], sample_size: int
) -> dict[str, int]:
    """Largest-remainder allocation from positive weights. Quotas sum to ``sample_size``."""
    if sample_size < 1:
        raise ValueError("sample_size must be >= 1")
    positive = {key: float(weight) for key, weight in weights.items() if float(weight) > 0}
    if not positive:
        raise ValueError("No positive weights for independent-marginal allocation")
    total = sum(positive.values())
    raw = {key: sample_size * (weight / total) for key, weight in positive.items()}
    floors = {key: int(value) for key, value in raw.items()}
    assigned = sum(floors.values())
    remainders = sorted(
        ((raw[key] - floors[key], key) for key in floors),
        key=lambda item: (-item[0], item[1]),
    )
    quotas = dict(floors)
    for index in range(sample_size - assigned):
        quotas[remainders[index][1]] += 1
    return quotas


def independent_marginal_cell_quotas(
    cells: list[dict[str, str]],
    sample_size: int,
    *,
    dimension_filters: dict[str, list[str]],
    marginals: dict[str, dict[str, float]] | None = None,
) -> list[int]:
    """Cell counts from the product of per-dimension marginals, Hamilton-rounded.

    Default marginal on each filter dim is equal share across its selected values.
    Cross-cell probability is ``a% × b% × c%``. Returned list aligns with ``cells``.
    """
    if sample_size < 1:
        raise ValueError("sample_size must be >= 1")
    if not cells:
        raise ValueError("no cells for independent-marginal allocation")
    probs: dict[str, dict[str, float]] = {}
    for dim, values in dimension_filters.items():
        raw = (marginals or {}).get(dim) or {}
        weights = [max(0.0, float(raw.get(value, 1.0))) for value in values]
        total = sum(weights)
        if total <= 0:
            weights = [1.0] * len(values)
            total = float(len(values))
        probs[dim] = {
            value: weight / total for value, weight in zip(values, weights, strict=True)
        }
    cell_weights: dict[str, float] = {}
    for index, cell in enumerate(cells):
        weight = 1.0
        for dim, value in cell.items():
            weight *= probs.get(dim, {}).get(value, 0.0)
        cell_weights[str(index)] = weight
    if sum(cell_weights.values()) <= 0:
        cell_weights = {key: 1.0 for key in cell_weights}
    allocated = hamilton_allocate_weights(cell_weights, sample_size)
    return [int(allocated.get(str(index), 0)) for index in range(len(cells))]


def normalize_overlay_dimensions(raw: list[Any] | None) -> list[dict[str, Any]]:
    """Cohort-scoped study dimensions (not part of the 1290 schema / Full-DAG)."""
    if not raw:
        return []
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for index, row in enumerate(raw):
        if not isinstance(row, dict):
            raise ValueError(f"overlay[{index}] must be an object")
        dim_id = str(row.get("id") or "").strip().lower().replace("-", "_")
        label = str(row.get("label") or "").strip() or dim_id
        values: list[str] = []
        seen_values: set[str] = set()
        for value in row.get("values") or []:
            text = str(value).strip()
            if not text or text in seen_values:
                continue
            seen_values.add(text)
            values.append(text)
        if not dim_id:
            raise ValueError(f"overlay[{index}] is missing id")
        if not OVERLAY_ID_RE.match(dim_id):
            raise ValueError(
                f"overlay[{index}] id {dim_id!r} must match {OVERLAY_ID_RE.pattern}"
            )
        if dim_id in seen:
            raise ValueError(f"duplicate overlay dimension id: {dim_id}")
        if not values:
            raise ValueError(f"overlay[{index}] ({dim_id}) needs at least one value")
        seen.add(dim_id)
        out.append({"id": dim_id, "label": label, "values": values})
    return out


def split_overlay_filters(
    dimension_filters: dict[str, list[str]],
    overlay_ids: set[str],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    catalog: dict[str, list[str]] = {}
    overlay: dict[str, list[str]] = {}
    for key, values in dimension_filters.items():
        target = overlay if key in overlay_ids else catalog
        target[key] = list(values)
    return catalog, overlay


def fill_overlay_filters(
    overlay: list[dict[str, Any]],
    overlay_filters: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Selected overlay values, or every defined value when the dim is unfiltered."""
    filled: dict[str, list[str]] = {}
    allowed = {str(row["id"]): list(row["values"]) for row in overlay}
    for dim_id, values in allowed.items():
        selected = [str(value) for value in overlay_filters.get(dim_id) or [] if str(value).strip()]
        filled[dim_id] = selected or list(values)
    return filled


def product_filter_cells(*filter_maps: dict[str, list[str]]) -> list[dict[str, str]]:
    merged: dict[str, list[str]] = {}
    for mapping in filter_maps:
        merged.update(mapping)
    if not merged:
        return [{}]
    return build_filter_strata(merged) or [{}]


def stamp_overlay_independent(
    personas: list[dict[str, Any]],
    overlay: list[dict[str, Any]],
    overlay_filters: dict[str, list[str]],
    *,
    seed: int,
) -> None:
    """Assign overlay attrs independently of the Full-DAG (in place)."""
    rng = random.Random(seed)
    for dim in overlay:
        values = overlay_filters.get(str(dim["id"])) or list(dim["values"])
        if not values:
            continue
        dim_id = str(dim["id"])
        for entry in personas:
            dims = entry.setdefault("dimensions", {})
            dims[dim_id] = rng.choice(values)


def stamp_overlay_from_cells(
    personas: list[dict[str, Any]],
    full_cells: list[dict[str, str]],
    quotas: list[int],
    overlay_ids: set[str],
) -> None:
    """Write overlay keys so cell counts match ``quotas`` (in place)."""
    used: set[int] = set()
    for cell, quota in zip(full_cells, quotas, strict=True):
        if quota <= 0:
            continue
        dag_part = {key: value for key, value in cell.items() if key not in overlay_ids}
        overlay_part = {key: value for key, value in cell.items() if key in overlay_ids}
        if not overlay_part:
            continue
        taken = 0
        for index, entry in enumerate(personas):
            if index in used or taken >= quota:
                continue
            dims = entry.setdefault("dimensions", {})
            if dag_part and not all(dims.get(key) == value for key, value in dag_part.items()):
                continue
            dims.update(overlay_part)
            used.add(index)
            taken += 1


def extend_cells_with_allowed_filters(
    cells: list[dict[str, str]],
    extra_filters: dict[str, list[str]],
    *,
    sampler: PersonaForwardSampler,
    max_tries_per_cell: int = 2048,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Pin one allowed value for each extra filter dim so rows survive ``dimensionFilters``."""
    if not extra_filters:
        return list(cells), []
    extra_dims = sorted(extra_filters)
    extra_values = [list(extra_filters[dim]) for dim in extra_dims]
    kept: list[dict[str, str]] = []
    dropped: list[dict[str, str]] = []
    for cell in cells:
        found: dict[str, str] | None = None
        for index, combo in enumerate(itertools.product(*extra_values)):
            if index >= max_tries_per_cell:
                break
            pinned = {**cell, **dict(zip(extra_dims, combo, strict=True))}
            if sampler.assignment_supported(pinned):
                found = pinned
                break
        if found is None:
            dropped.append(cell)
        else:
            kept.append(found)
    return kept, dropped


def extra_filters_from_strategy(
    dimension_filters: dict[str, list[str]],
    stratify_fields: list[str] | None,
) -> dict[str, list[str]]:
    """Filter dims that constrain generation but are not stratify axes."""
    axes = {
        str(field).removeprefix("dimensions.").strip()
        for field in (stratify_fields or [])
        if str(field).strip()
    }
    if not axes:
        return {}
    return {
        key: list(values)
        for key, values in dimension_filters.items()
        if key not in axes
    }


def strategy_pin_cells(
    *,
    dimension_filters: dict[str, list[str]],
    stratify_fields: list[str] | None = None,
    sampler: PersonaForwardSampler | None = None,
    seed: int = 42,
    max_strata: int = 2048,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Return stratify cells Playground will bucket on.

    Other ``dimensionFilters`` must still have at least one DAG-supported
    combination per cell; those extra dims are not pinned here. Generation
    draws them per person from the allowed set.
    """
    dag = sampler or _dag_sampler(seed=seed)
    fields = [
        str(field).removeprefix("dimensions.").strip()
        for field in (stratify_fields or [])
        if str(field).strip()
    ]
    if fields:
        axes = {field: list(dimension_filters[field]) for field in fields}
    else:
        axes = dict(dimension_filters)
    cells = build_filter_strata(axes, max_strata=max_strata)
    cells, dropped = filter_strata_on_dag(cells, sampler=dag)
    extra = {
        key: list(values)
        for key, values in dimension_filters.items()
        if key not in axes
    }
    if extra:
        feasible: list[dict[str, str]] = []
        for cell in cells:
            if supported_extra_assignments(cell, extra, sampler=dag):
                feasible.append(cell)
            else:
                dropped.append(cell)
        cells = feasible
    return cells, dropped


def generate_persona_pool(
    *,
    count: int,
    seed: int = 42,
    smoke_persona_id: str = "0042",
    stratum_top_up: list[dict[str, str]] | None = None,
    min_per_stratum: int = 0,
    extra_filters: dict[str, list[str]] | None = None,
    cell_quotas: list[int] | None = None,
    persona_version: str = DEFAULT_PERSONA_VERSION,
    include_smoke: bool = True,
) -> list[dict[str, Any]]:
    """Sample ``count`` synthetic personas from the Full DAG.

    ``count`` may be ``0`` to only fill ``stratum_top_up`` cells (each DAG-supported
    cell gets at least ``min_per_stratum`` rows, or ``cell_quotas`` when set).
    """
    if count < 0:
        raise ValueError("count must be >= 0")
    dag = _dag_sampler(seed=seed)
    extras = extra_filters or {}
    extra_assignments: list[dict[str, str]] | None = None
    if extras and count:
        extra_assignments = supported_extra_assignments({}, extras, sampler=dag)
        if not extra_assignments:
            raise ValueError("dimensionFilters produced zero cells the DAG can pin")

    personas: list[dict[str, Any]] = []
    if count and extra_assignments:
        rng = random.Random(seed)
        buckets: dict[tuple[tuple[str, str], ...], int] = {}
        pin_by_key: dict[tuple[tuple[str, str], ...], dict[str, str]] = {}
        for _ in range(count):
            pin = rng.choice(extra_assignments)
            key = tuple(sorted(pin.items()))
            pin_by_key[key] = pin
            buckets[key] = buckets.get(key, 0) + 1
        next_id = 1
        for key, n in buckets.items():
            for row in dag.sample(n, fixed=pin_by_key[key]):
                personas.append(
                    _persona_entry(
                        persona_id=str(next_id).zfill(4),
                        dimensions=dict(row),
                        version=persona_version,
                    )
                )
                next_id += 1
    else:
        for index, row in enumerate(dag.sample(count) if count else [], start=1):
            personas.append(
                _persona_entry(
                    persona_id=str(index).zfill(4),
                    dimensions=dict(row),
                    version=persona_version,
                )
            )

    should_top = bool(stratum_top_up) and (
        min_per_stratum > 0
        or (cell_quotas is not None and any(quota > 0 for quota in cell_quotas))
    )
    if should_top:
        kept, dropped = filter_strata_on_dag(stratum_top_up or [], sampler=dag)
        del dropped
        kept_quotas = None
        if cell_quotas is not None and stratum_top_up:
            quota_by_key = {
                tuple(sorted(cell.items())): quota
                for cell, quota in zip(stratum_top_up, cell_quotas, strict=True)
            }
            kept_quotas = [
                int(quota_by_key.get(tuple(sorted(cell.items())), 0)) for cell in kept
            ]
        personas = top_up_strata(
            personas,
            strata=kept,
            min_per_stratum=min_per_stratum,
            persona_version=persona_version,
            sampler=dag,
            seed=seed,
            extra_filters=extra_filters,
            cell_quotas=kept_quotas,
        )

    if include_smoke:
        if any(entry["persona_id"] == smoke_persona_id for entry in personas):
            return personas
        smoke_fixed = None
        if extra_assignments:
            smoke_fixed = random.Random(seed + 17).choice(extra_assignments)
        smoke_entry = _persona_entry(
            persona_id=smoke_persona_id,
            dimensions=dict(dag.sample(1, fixed=smoke_fixed)[0]),
            version=persona_version,
        )
        if not personas:
            return [smoke_entry]
        smoke_index = int(smoke_persona_id) - 1
        if 0 <= smoke_index < len(personas):
            personas[smoke_index] = smoke_entry
            return personas
        personas.append(smoke_entry)
    return personas


def parse_overlay_cli(raw: str) -> dict[str, Any]:
    """Parse ``id[:label]=v1,v2`` used by generate CLI and docs."""
    text = str(raw).strip()
    if "=" not in text:
        raise ValueError("overlay must be id[:label]=value,value")
    head, values_raw = text.split("=", 1)
    head = head.strip()
    if not head:
        raise ValueError("overlay is missing id")
    if ":" in head:
        dim_id, label = head.split(":", 1)
    else:
        dim_id, label = head, head
    values = [part.strip() for part in values_raw.split(",") if part.strip()]
    return {"id": dim_id.strip(), "label": label.strip(), "values": values}


def parse_filter_cli(raw: str) -> tuple[str, list[str]]:
    """Parse ``dim=v1,v2`` used by generate CLI and docs."""
    text = str(raw).strip()
    if "=" not in text:
        raise ValueError("filter must be dimension=value,value")
    dim, values_raw = text.split("=", 1)
    dim_id = dim.removeprefix("dimensions.").strip()
    values = [part.strip() for part in values_raw.split(",") if part.strip()]
    if not dim_id:
        raise ValueError("filter is missing dimension id")
    if not values:
        raise ValueError(f"filter {dim_id!r} needs at least one value")
    return dim_id, values


def parse_marginal_cli(raw: str) -> tuple[str, dict[str, float]]:
    """Parse ``dim=v1:w1,v2:w2`` share weights for By share / independentMarginal.

    Weights may be any positive numbers (percentages or relative weights). Missing
    selected filter values default to equal share in allocation.
    """
    text = str(raw).strip()
    if "=" not in text:
        raise ValueError("marginal must be dimension=value:weight,value:weight")
    dim, weights_raw = text.split("=", 1)
    dim_id = dim.removeprefix("dimensions.").strip()
    if not dim_id:
        raise ValueError("marginal is missing dimension id")
    weights: dict[str, float] = {}
    for part in weights_raw.split(","):
        item = part.strip()
        if not item:
            continue
        if ":" not in item:
            raise ValueError(
                f"marginal {dim_id!r} entry {item!r} must be value:weight"
            )
        value, weight_raw = item.rsplit(":", 1)
        value = value.strip()
        weight_raw = weight_raw.strip()
        if not value:
            raise ValueError(f"marginal {dim_id!r} has an empty value")
        try:
            weight = float(weight_raw)
        except ValueError as exc:
            raise ValueError(
                f"marginal {dim_id!r} weight for {value!r} must be a number"
            ) from exc
        if weight <= 0:
            raise ValueError(
                f"marginal {dim_id!r} weight for {value!r} must be > 0"
            )
        weights[value] = weight
    if not weights:
        raise ValueError(f"marginal {dim_id!r} needs at least one value:weight")
    return dim_id, weights


def overlay_dimensions_from_manifest(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    raw = payload.get("overlay_dimensions")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        dim_id = str(row.get("id") or "").strip()
        if not dim_id:
            continue
        values = [str(value) for value in (row.get("values") or []) if str(value).strip()]
        label = str(row.get("label") or "").strip() or dim_id
        item: dict[str, Any] = {"id": dim_id, "label": label, "values": values}
        out.append(item)
    return out


def _contrast_id_suffix(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "value"


def resolve_contrast_overlay(
    overlay: list[dict[str, Any]],
    overlay_id: str,
    value: str,
    *,
    schema_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Return the overlay row for a contrast stamp, or raise ``ValueError``."""
    dim_id = str(overlay_id or "").strip().lower().replace("-", "_")
    text = str(value or "").strip()
    if not dim_id:
        raise ValueError("contrast dimension is required")
    if not text:
        raise ValueError("contrast value is required")
    if schema_ids and dim_id in schema_ids:
        return {"id": dim_id, "label": dim_id, "values": [text]}
    for row in overlay:
        if str(row.get("id") or "").strip() != dim_id:
            continue
        allowed = [str(item) for item in (row.get("values") or []) if str(item).strip()]
        if text not in allowed:
            raise ValueError(
                f"{text!r} is not an allowed value for custom dimension {dim_id!r}"
            )
        return row
    raise ValueError(
        f"custom dimension {dim_id!r} is not on this dataset; "
        "generate a pool with that dimension first"
    )


def normalize_generate_contrast(
    overlay: list[dict[str, Any]] | None,
    contrast: list[Any] | None,
    *,
    schema_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Validate generate-time contrast arms.

    Each arm is one dimension: keep the first pool as filtered, then clone
    extra ``values``. Several arms combine (one copy per value combination).
    """
    if not contrast:
        return []
    rows = normalize_overlay_dimensions(overlay)
    by_id: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(contrast):
        if not isinstance(raw, dict):
            raise ValueError(f"contrast[{index}] must be an object")
        overlay_id = str(
            raw.get("overlayId") or raw.get("overlay_id") or raw.get("id") or ""
        ).strip()
        base = str(
            raw.get("baseValue")
            or raw.get("base")
            or raw.get("base_value")
            or ""
        ).strip()
        extras_raw = raw.get("values")
        if extras_raw is None:
            extras_raw = raw.get("extra") or []
        if not isinstance(extras_raw, list):
            raise ValueError(f"contrast[{index}] values must be a list")
        if not overlay_id:
            raise ValueError(f"contrast[{index}] overlayId is required")
        extras: list[str] = []
        seen: set[str] = set()
        for item in extras_raw:
            text = str(item).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            extras.append(text)
        if not extras:
            continue
        if not base:
            base = extras[0]
        dim = resolve_contrast_overlay(rows, overlay_id, base, schema_ids=schema_ids)
        for text in extras:
            resolve_contrast_overlay(rows, overlay_id, text, schema_ids=schema_ids)
        dim_id = str(dim["id"])
        existing = by_id.get(dim_id)
        if existing is None:
            by_id[dim_id] = {
                "id": dim_id,
                "label": dim.get("label") or dim_id,
                "base": base,
                "values": extras,
            }
            continue
        for text in extras:
            if text != existing["base"] and text not in existing["values"]:
                existing["values"].append(text)
    return list(by_id.values())


def contrast_stamp_combinations(
    plan: list[dict[str, Any]] | None,
) -> list[dict[str, str]]:
    """One stamp map per cartesian combination of contrast-arm values."""
    if not plan:
        return []
    ids = [str(arm["id"]) for arm in plan]
    value_lists = [list(arm["values"]) for arm in plan]
    if not ids or any(not values for values in value_lists):
        return []
    return [
        {ids[index]: str(combo[index]) for index in range(len(ids))}
        for combo in itertools.product(*value_lists)
    ]


def contrast_base_stamps(plan: list[dict[str, Any]] | None) -> dict[str, str]:
    """Stamp map for the first contrast pool (each arm's ``base`` value)."""
    if not plan:
        return {}
    out: dict[str, str] = {}
    for arm in plan:
        dim_id = str(arm.get("id") or "").strip()
        base = str(arm.get("base") or "").strip()
        if dim_id and base:
            out[dim_id] = base
    return out


def apply_dimension_stamps(
    personas: list[dict[str, Any]],
    stamps: dict[str, str],
) -> None:
    """Set dimension values in place without rewriting persona ids."""
    mapping = {
        str(key).strip().lower().replace("-", "_"): str(value).strip()
        for key, value in stamps.items()
        if str(key).strip() and str(value).strip()
    }
    if not mapping:
        return
    for entry in personas:
        dims = entry.get("dimensions")
        if not isinstance(dims, dict):
            dims = {}
            entry["dimensions"] = dims
        dims.update(mapping)


def clone_contrast_personas(
    personas: list[dict[str, Any]],
    *,
    overlay_id: str | None = None,
    value: str | None = None,
    stamps: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Copy each persona and change only the stamped dimension values."""
    mapping: dict[str, str] = {}
    if stamps:
        for key, item in stamps.items():
            dim_id = str(key or "").strip().lower().replace("-", "_")
            text = str(item or "").strip()
            if dim_id and text:
                mapping[dim_id] = text
    if overlay_id and value:
        dim_id = str(overlay_id or "").strip().lower().replace("-", "_")
        text = str(value or "").strip()
        if dim_id and text:
            mapping[dim_id] = text
    if not mapping:
        raise ValueError("contrast dimension and value are required")
    suffix = "-".join(_contrast_id_suffix(text) for text in mapping.values())
    cloned: list[dict[str, Any]] = []
    for entry in personas:
        dims = dict(entry.get("dimensions") or {})
        dims.update(mapping)
        base_id = str(entry.get("persona_id") or "persona")
        pair_id = str(entry.get("pair_id") or base_id)
        cloned.append(
            {
                "persona_id": f"{base_id}-c-{suffix}",
                "version": entry.get("version", DEFAULT_PERSONA_VERSION),
                "source": entry.get("source", SYNTHETIC_SOURCE),
                "dimensions": dims,
                "pair_id": pair_id,
                "contrast_from": base_id,
            }
        )
    return cloned


def validate_contrast_stamps_against_dag(
    personas: list[dict[str, Any]],
    stamps: dict[str, str],
    *,
    schema_ids: set[str] | None = None,
    sampler: PersonaForwardSampler | None = None,
    seed: int = 42,
) -> None:
    """Ensure stamped schema dims stay DAG-supported on each persona (no resample).

    Custom overlay stamps are ignored. Raises ``ValueError`` when any persona's
    dimensions after stamp violate a Full-DAG hard mask.
    """
    mapping: dict[str, str] = {}
    for key, item in stamps.items():
        dim_id = str(key or "").strip().lower().replace("-", "_")
        text = str(item or "").strip()
        if not dim_id or not text:
            continue
        if schema_ids is not None and dim_id not in schema_ids:
            continue
        mapping[dim_id] = text
    if not mapping or not personas:
        return
    dag = sampler or _dag_sampler(seed=seed)
    label = ", ".join(f"{key}={value}" for key, value in sorted(mapping.items()))
    for entry in personas:
        dims = {
            str(key): str(value)
            for key, value in (entry.get("dimensions") or {}).items()
            if str(key).strip() and str(value).strip()
        }
        dims.update(mapping)
        if dag.assignment_supported(dims):
            continue
        persona_id = str(entry.get("persona_id") or "persona")
        raise ValueError(
            f"Contrast stamps [{label}] are not Full-DAG-supported for persona "
            f"{persona_id} (hard mask with other dimensions). "
            "Pick different contrast attributes or shared filters."
        )


@dataclass
class SyntheticGenerateResult:
    personas: list[dict[str, Any]]
    overlay: list[dict[str, Any]]
    folder_count: int


def generate_synthetic_personas(
    *,
    count: int | None = None,
    seed: int = 42,
    dimension_filters: dict[str, list[str]] | None = None,
    stratify_fields: list[str] | None = None,
    allocation: str | None = None,
    per_cell: int | None = None,
    sample_size: int | None = None,
    marginals: dict[str, dict[str, float]] | None = None,
    overlay_dimensions: list[dict[str, Any]] | None = None,
    catalog_path: str | Path | None = None,
    force_pin: bool = False,
    count_default: int = GENERATE_COUNT_DEFAULT,
    count_max: int = GENERATE_COUNT_MAX,
    max_strata: int = MAX_FILTER_STRATA,
) -> SyntheticGenerateResult:
    """Full-DAG sample plus overlay stamp. Shared by Playground generate and CLI."""
    filters = {
        str(key).removeprefix("dimensions.").strip(): [str(value) for value in values]
        for key, values in (dimension_filters or {}).items()
        if str(key).removeprefix("dimensions.").strip() and values
    }
    fields = [
        str(field).removeprefix("dimensions.").strip()
        for field in (stratify_fields or [])
        if str(field).strip()
    ]
    alloc = str(allocation or "").strip() or None
    per_cell_n = per_cell if isinstance(per_cell, int) and per_cell >= 1 else None
    sample_n = sample_size if isinstance(sample_size, int) and sample_size >= 1 else None

    overlay = normalize_overlay_dimensions(overlay_dimensions)
    overlay_ids = {str(row["id"]) for row in overlay}
    if overlay:
        catalog = load_catalog_values(catalog_path)
        colliding = sorted(overlay_ids & set(catalog))
        if colliding:
            raise ValueError(
                "overlay id collides with a persona dimension: " + ", ".join(colliding)
            )

    catalog_filters, overlay_raw_filters = split_overlay_filters(filters, overlay_ids)
    overlay_filters = fill_overlay_filters(overlay, overlay_raw_filters) if overlay else {}
    catalog_fields = [field for field in fields if field not in overlay_ids]
    overlay_fields = [field for field in fields if field in overlay_ids]
    missing = [field for field in catalog_fields if field not in catalog_filters]
    missing.extend(field for field in overlay_fields if field not in overlay_filters)
    if missing:
        raise ValueError(
            "every sampling field must also appear in filters "
            f"(missing: {', '.join(missing)})"
        )

    stratum_top_up: list[dict[str, str]] | None = None
    min_per_stratum = 0
    cell_quotas: list[int] | None = None
    pool_count = 0
    full_cells: list[dict[str, str]] | None = None
    full_quotas: list[int] | None = None
    pin_cells = bool(force_pin) or bool(catalog_fields) or bool(catalog_filters and alloc)
    overlay_grid = bool(overlay_fields)
    overlay_axis_filters = (
        {key: list(overlay_filters[key]) for key in overlay_fields}
        if overlay_fields
        else {}
    )

    if pin_cells:
        if not catalog_filters:
            raise ValueError("stratified generation requires filters")
        cells, _dropped = strategy_pin_cells(
            dimension_filters=catalog_filters,
            stratify_fields=catalog_fields,
            seed=seed,
            max_strata=max_strata,
        )
        if not cells:
            raise ValueError("filters produced zero cells the DAG can pin")
        if overlay_grid:
            overlay_cells = product_filter_cells(overlay_axis_filters)
            full_cells = [
                {**dag_cell, **overlay_cell}
                for dag_cell in cells
                for overlay_cell in overlay_cells
            ]
            grid_filters = {**catalog_filters, **overlay_axis_filters}
            if alloc == "independentMarginal":
                if not isinstance(sample_n, int) or sample_n < 1:
                    raise ValueError(
                        'allocation "independentMarginal" requires sampleSize >= 1'
                    )
                full_quotas = independent_marginal_cell_quotas(
                    full_cells,
                    sample_n,
                    dimension_filters=grid_filters,
                    marginals=marginals,
                )
                estimated = sample_n
                dag_quota_map: dict[tuple[tuple[str, str], ...], int] = {}
                dag_order: list[tuple[tuple[str, str], ...]] = []
                for cell, quota in zip(full_cells, full_quotas, strict=True):
                    key = tuple(
                        sorted(
                            (dim, value)
                            for dim, value in cell.items()
                            if dim not in overlay_ids
                        )
                    )
                    if key not in dag_quota_map:
                        dag_order.append(key)
                        dag_quota_map[key] = 0
                    dag_quota_map[key] += int(quota)
                stratum_top_up = [dict(key) for key in dag_order]
                cell_quotas = [dag_quota_map[key] for key in dag_order]
                min_per_stratum = 0
            else:
                min_full = stratified_cell_quota(
                    allocation=alloc,
                    per_cell=per_cell_n,
                    sample_size=sample_n,
                    n_cells=len(full_cells),
                )
                estimated = len(full_cells) * min_full
                full_quotas = [min_full] * len(full_cells)
                min_per_stratum = min_full * len(overlay_cells)
                stratum_top_up = cells
            if estimated > count_max:
                raise ValueError(
                    f"stratified generation would write {estimated} personas "
                    f"(max {count_max})"
                )
            pool_count = 0
        elif alloc == "independentMarginal":
            if not isinstance(sample_n, int) or sample_n < 1:
                raise ValueError(
                    'allocation "independentMarginal" requires sampleSize >= 1'
                )
            cell_quotas = independent_marginal_cell_quotas(
                cells,
                sample_n,
                dimension_filters=catalog_filters,
                marginals=marginals,
            )
            estimated = sample_n
            if estimated > count_max:
                raise ValueError(
                    f"stratified generation would write {estimated} personas "
                    f"(max {count_max})"
                )
            stratum_top_up = cells
            pool_count = 0
        else:
            min_per_stratum = stratified_cell_quota(
                allocation=alloc,
                per_cell=per_cell_n,
                sample_size=sample_n,
                n_cells=len(cells),
            )
            estimated = len(cells) * min_per_stratum
            if estimated > count_max:
                raise ValueError(
                    f"stratified generation would write {estimated} personas "
                    f"(max {count_max})"
                )
            stratum_top_up = cells
            pool_count = 0
    elif overlay_grid:
        full_cells = product_filter_cells(overlay_axis_filters)
        if alloc == "independentMarginal":
            if not isinstance(sample_n, int) or sample_n < 1:
                raise ValueError(
                    'allocation "independentMarginal" requires sampleSize >= 1'
                )
            full_quotas = independent_marginal_cell_quotas(
                full_cells,
                sample_n,
                dimension_filters=overlay_axis_filters,
                marginals=marginals,
            )
            pool_count = sample_n
        else:
            min_full = stratified_cell_quota(
                allocation=alloc,
                per_cell=per_cell_n,
                sample_size=sample_n,
                n_cells=len(full_cells),
            )
            full_quotas = [min_full] * len(full_cells)
            pool_count = len(full_cells) * min_full
        if pool_count < 1:
            raise ValueError("count must be >= 1")
        if pool_count > count_max:
            raise ValueError(f"count must be <= {count_max}")
    else:
        pool_count = count_default if count is None else int(count)
        if pool_count < 1:
            raise ValueError("count must be >= 1")
        if pool_count > count_max:
            raise ValueError(f"count must be <= {count_max}")

    extra_filters = (
        extra_filters_from_strategy(catalog_filters, catalog_fields)
        if pin_cells
        else catalog_filters
    )
    personas = generate_persona_pool(
        count=pool_count,
        seed=seed,
        stratum_top_up=stratum_top_up,
        min_per_stratum=min_per_stratum,
        extra_filters=extra_filters or None,
        cell_quotas=cell_quotas,
        include_smoke=pool_count > 0 and not overlay_grid,
    )
    if not personas:
        raise ValueError("generation produced no personas")
    if overlay:
        if full_cells is not None and full_quotas is not None:
            stamp_overlay_from_cells(personas, full_cells, full_quotas, overlay_ids)
        leftover = [
            row
            for row in overlay
            if full_cells is None or str(row["id"]) not in overlay_fields
        ]
        if leftover:
            stamp_overlay_independent(
                personas,
                leftover,
                overlay_filters,
                seed=seed + 1,
            )
        rng = random.Random(seed + 2)
        for row in overlay:
            values = overlay_filters.get(str(row["id"])) or list(row["values"])
            if not values:
                continue
            dim_id = str(row["id"])
            for entry in personas:
                dims = entry.setdefault("dimensions", {})
                if dim_id not in dims:
                    dims[dim_id] = rng.choice(values)
    return SyntheticGenerateResult(
        personas=personas,
        overlay=overlay,
        folder_count=pool_count,
    )


def write_persona_dataset(
    *,
    out_dir: Path,
    personas: list[dict[str, Any]],
    repo_root: Path,
    kind: str,
    seed: int,
    smoke_persona_id: str,
    catalog_path: str = DEFAULT_CATALOG_PATH,
    persona_version: str = DEFAULT_PERSONA_VERSION,
    manifest_name: str | None = None,
    manifest_description: str | None = None,
    overlay_dimensions: list[dict[str, Any]] | None = None,
    extra_manifest: dict[str, Any] | None = None,
    on_progress: Callable[[str, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Write one YAML per persona + ``manifest.json``.

    ``on_progress(stage, payload)`` is optional. Stages: ``write`` (with
    ``done``/``total``) and ``manifest``.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    if personas:
        dimension_ids = list(personas[0]["dimensions"])
    else:
        dimension_ids = list(load_dev_dimension_ids(catalog_path=catalog_path))
    manifest_personas: list[dict[str, Any]] = []
    total = len(personas)
    # ~40 updates max so large pools stay responsive without flooding the wire.
    report_every = max(1, total // 40) if total else 1
    for index, entry in enumerate(personas, start=1):
        persona_id = entry["persona_id"]
        rel_path = f"{out_dir.relative_to(repo_root)}/persona_{persona_id}.yaml"
        payload = {
            "persona_id": persona_id,
            "version": entry.get("version", persona_version),
            "source": entry.get("source"),
            "dimensions": entry["dimensions"],
        }
        if entry.get("pair_id"):
            payload["pair_id"] = entry["pair_id"]
        if entry.get("contrast_from"):
            payload["contrast_from"] = entry["contrast_from"]
        (repo_root / rel_path).write_text(
            yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
        )
        manifest_row = {
            "persona_id": persona_id,
            "path": rel_path,
            "source": entry.get("source"),
            "dimensions": entry["dimensions"],
        }
        if entry.get("pair_id"):
            manifest_row["pair_id"] = entry["pair_id"]
        if entry.get("contrast_from"):
            manifest_row["contrast_from"] = entry["contrast_from"]
        manifest_personas.append(manifest_row)
        if on_progress and (index == total or index % report_every == 0):
            on_progress(
                "write",
                {
                    "done": index,
                    "total": total,
                    "label": f"Writing personas ({index}/{total})",
                },
            )

    source_counts: dict[str, int] = {}
    for entry in manifest_personas:
        source = entry.get("source")
        if source:
            source_counts[source] = source_counts.get(source, 0) + 1

    if on_progress:
        on_progress("manifest", {"label": "Writing manifest…"})

    manifest: dict[str, Any] = {
        "kind": kind,
        "count": len(manifest_personas),
        "seed": seed,
        "schema_version": persona_version,
        "smoke_persona_id": smoke_persona_id,
        "dimension_ids": list(dimension_ids),
        "dimension_count": len(dimension_ids),
        "dimension_categories": "persona/schema/dimension_categories.json",
        "persona_sources": sorted(source_counts),
        "source_counts": source_counts,
        "personas": manifest_personas,
    }
    if manifest_name:
        manifest["name"] = manifest_name
    if manifest_description:
        manifest["description"] = manifest_description
    if overlay_dimensions:
        manifest["overlay_dimensions"] = list(overlay_dimensions)
    if extra_manifest:
        for key, value in extra_manifest.items():
            if value is not None:
                manifest[key] = value
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest
