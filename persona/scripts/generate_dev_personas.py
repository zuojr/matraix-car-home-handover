#!/usr/bin/env python3
"""Write a synthetic persona pool you can pick in Playground Dataset.

Same path as Playground Generation. Default: ``--count`` rows (2000) into
``persona/datasets/generated-persona-dev-<count>/``.

``--overlay id[:label]=v1,v2`` adds custom dimensions. ``--filter`` is
Independent; ``--contrast-filter`` / ``--contrast`` are Contrast (base-value
pool + one dataset per selected value combination). Progress: one bar per
dataset.

Sampling (same labels as the UI): ``--count`` (Random), ``--per-cell``
(By combo), ``--sample-size`` (By share). Optional ``--marginal`` /
``--contrast-marginal`` for By-share weights (omit = equal).

``--strategy PATH`` fills ``persona_strategy.json`` (filters, allocation, and
declared mix via ``sampling.portions`` or weighted ``dimensionFilters``).
``--task PATH --per-cell N`` fills grounding.toml probe cells only.
``--contrast-from POOL`` clones an existing dataset (``--contrast-dim`` /
``--contrast-value`` for a single arm).

See docs/persona/README.md § Playground Generation.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

from matraix.persona_dimension_catalog import values_for_dimension
from matraix.persona_consistency import load_dev_dimension_ids
from matraix.persona_generator import (
    GENERATE_COUNT_DEFAULT,
    GENERATE_COUNT_MAX,
    apply_dimension_stamps,
    build_probe_strata,
    clone_contrast_personas,
    contrast_base_stamps,
    contrast_stamp_combinations,
    fill_overlay_filters,
    generate_persona_pool,
    generate_synthetic_personas,
    normalize_generate_contrast,
    normalize_overlay_dimensions,
    overlay_dimensions_from_manifest,
    parse_filter_cli,
    parse_marginal_cli,
    parse_overlay_cli,
    resolve_contrast_overlay,
    stamp_overlay_independent,
    validate_contrast_stamps_against_dag,
    write_persona_dataset,
)
from matraix.persona_job import load_manifest
from matraix.task_catalog import (
    confounder_values_from_grounding,
    get_task_grounding_spec,
    probe_dimension_from_grounding,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASETS_DIR = REPO_ROOT / "persona" / "datasets"
DEFAULT_POOL_PREFIX = "generated-persona-dev"
_DATASETS_SKIP_TOP_LEVEL = frozenset(
    {"_generated", "_sampled", "cohorts", "saved-cohorts", "matraix-persona-1m"}
)


def _default_out_dir(count: int) -> Path:
    return DATASETS_DIR / f"{DEFAULT_POOL_PREFIX}-{count}"


def _strategy_out_dir(task_slug: str) -> Path:
    return DATASETS_DIR / f"{DEFAULT_POOL_PREFIX}-strategy-{task_slug}"


def _is_picker_listed(out: Path) -> bool:
    try:
        rel = out.resolve().relative_to(DATASETS_DIR.resolve())
    except ValueError:
        return False
    return len(rel.parts) == 1 and rel.parts[0] not in _DATASETS_SKIP_TOP_LEVEL


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "strategy"


def _progress(stage: str, message: str) -> None:
    print(f"[{stage}] {message}", flush=True)


class _DatasetProgressBars:
    """N terminal progress bars — one per dataset being written."""

    def __init__(self, labels: list[str]) -> None:
        self.labels = [str(label) for label in labels]
        self.ratios = [0.0] * len(self.labels)
        self.details = ["waiting"] * len(self.labels)
        self._drawn = 0
        self._last_printed_pct = [-1] * len(self.labels)
        self._tty = sys.stdout.isatty()
        if self.labels:
            print(f"[plan] Writing {len(self.labels)} dataset(s):", flush=True)
            for index, label in enumerate(self.labels, start=1):
                print(f"  {index}. {label}", flush=True)

    def update(
        self,
        index: int,
        *,
        ratio: float,
        detail: str | None = None,
        label: str | None = None,
    ) -> None:
        if index < 0 or index >= len(self.labels):
            return
        self.ratios[index] = max(0.0, min(1.0, float(ratio)))
        if detail:
            self.details[index] = str(detail)
        if label:
            self.labels[index] = str(label)
        self._render()

    def complete(self, index: int) -> None:
        self.update(index, ratio=1.0, detail="done")

    def _bar(self, ratio: float, width: int = 20) -> str:
        filled = int(round(ratio * width))
        return "█" * filled + "░" * (width - filled)

    def _line(self, index: int) -> str:
        pct = int(round(self.ratios[index] * 100))
        label = self.labels[index]
        short = label if len(label) <= 36 else label[:33] + "..."
        return (
            f"  [{index + 1}/{len(self.labels)}] {short:<36} "
            f"|{self._bar(self.ratios[index])}| {pct:3d}%  {self.details[index]}"
        )

    def _render(self) -> None:
        if not self.labels:
            return
        if self._tty:
            if self._drawn:
                sys.stdout.write(f"\033[{self._drawn}A")
            block = "\n".join(self._line(i) for i in range(len(self.labels)))
            sys.stdout.write(block + "\n")
            sys.stdout.flush()
            self._drawn = len(self.labels)
            return
        # Non-TTY: print each bar at 0/25/50/75/100 milestones.
        for index in range(len(self.labels)):
            pct = int(round(self.ratios[index] * 100))
            milestone = (
                pct
                if pct in {0, 25, 50, 75, 100} or self.ratios[index] >= 1.0
                else None
            )
            if milestone is None or milestone == self._last_printed_pct[index]:
                continue
            self._last_printed_pct[index] = milestone
            print(self._line(index), flush=True)


def _write_progress(stage: str, payload: dict) -> None:
    label = str(payload.get("label") or stage)
    if stage == "write":
        done = int(payload.get("done") or 0)
        total = int(payload.get("total") or 0)
        if total > 0:
            pct = round(100 * done / total)
            _progress("write", f"{label} ({pct}%)")
            return
    _progress(stage, label)


def _wipe_stale_personas(out: Path) -> int:
    if not out.is_dir():
        return 0
    removed = 0
    for stale in out.glob("persona_*.yaml"):
        stale.unlink()
        removed += 1
    return removed


def _stratum_top_up_from_task(
    task_path: str,
) -> tuple[list[dict[str, str]], dict[str, object]]:
    grounding = get_task_grounding_spec(task_path, repo_root=REPO_ROOT)
    if not grounding:
        raise SystemExit(f"No grounding.toml (or catalog grounding) for {task_path!r}")
    confounders = confounder_values_from_grounding(grounding)
    probe_dimension = probe_dimension_from_grounding(grounding)
    if not confounders or not probe_dimension:
        raise SystemExit(
            f"Task {task_path!r} grounding must define confounders and probe_dimension"
        )
    probe_key = probe_dimension.removeprefix("dimensions.")
    probe_values = values_for_dimension(probe_key)
    if not probe_values:
        raise SystemExit(f"No catalog values for probe dimension {probe_key!r}")
    return build_probe_strata(
        confounders=confounders,
        probe_dimension=probe_dimension,
        probe_values=probe_values,
    ), grounding


def _resolve_strategy_path(raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = REPO_ROOT / path
    if path.is_dir():
        candidate = path / "persona_strategy.json"
        if not candidate.is_file():
            raise SystemExit(f"No persona_strategy.json under {path}")
        return candidate
    if path.is_file():
        return path
    raise SystemExit(f"Strategy path not found: {raw}")


def _as_portions(value: object) -> dict[str, dict[str, float]]:
    """``{dimension: {value: weight}}`` — same shape as Playground ``sampling.portions``."""
    if not isinstance(value, dict):
        return {}
    out: dict[str, dict[str, float]] = {}
    for dim, weights in value.items():
        dim_name = str(dim).removeprefix("dimensions.").strip()
        if not dim_name or not isinstance(weights, dict):
            continue
        coerced: dict[str, float] = {}
        for label, weight in weights.items():
            key = str(label).strip()
            if not key or isinstance(weight, bool) or not isinstance(weight, (int, float)):
                continue
            if float(weight) > 0:
                coerced[key] = float(weight)
        if coerced:
            out[dim_name] = coerced
    return out


def _load_strategy(path: Path) -> dict[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Failed to read strategy {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SystemExit(f"Strategy {path} must be a JSON object")
    filters = raw.get("dimensionFilters") or {}
    if not isinstance(filters, dict):
        filters = {}
    normalized_filters: dict[str, list[str]] = {}
    derived_portions: dict[str, dict[str, float]] = {}
    for key, values in filters.items():
        dim = str(key).removeprefix("dimensions.").strip()
        if not dim:
            continue
        if isinstance(values, dict):
            weights = _as_portions({dim: values}).get(dim, {})
            cleaned = list(weights) if weights else [
                str(label).strip() for label in values if str(label).strip()
            ]
            if cleaned:
                normalized_filters[dim] = cleaned
            if weights:
                derived_portions[dim] = weights
            continue
        if isinstance(values, list):
            cleaned = [str(value).strip() for value in values if str(value).strip()]
        else:
            text = str(values).strip()
            cleaned = [text] if text else []
        if cleaned:
            normalized_filters[dim] = cleaned
    sampling = raw.get("sampling") if isinstance(raw.get("sampling"), dict) else {}
    stratify = sampling.get("fields") or []
    if not isinstance(stratify, list):
        stratify = []
    per_group = sampling.get("perCell")
    sample_size = sampling.get("sampleSize")
    portions = _as_portions(sampling.get("portions")) or derived_portions
    block: dict[str, object] = {
        "mode": str(sampling.get("mode") or "random"),
        "fields": [str(field).strip() for field in stratify if str(field).strip()],
        "allocation": sampling.get("allocation"),
        "perCell": per_group if isinstance(per_group, int) else None,
        "sampleSize": sample_size if isinstance(sample_size, int) else None,
    }
    if portions:
        block["portions"] = portions
    return {
        "dimensionFilters": normalized_filters,
        "sampling": block,
    }


def _parse_overlays(raw: list[str]) -> list[dict[str, object]]:
    overlay: list[dict[str, object]] = []
    for item in raw:
        try:
            overlay.append(parse_overlay_cli(item))
        except ValueError as exc:
            raise SystemExit(f"--overlay {item!r}: {exc}") from exc
    try:
        return normalize_overlay_dimensions(overlay)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


def _parse_filters(raw: list[str], *, flag: str = "--filter") -> dict[str, list[str]]:
    filters: dict[str, list[str]] = {}
    for item in raw:
        try:
            dim_id, values = parse_filter_cli(item)
        except ValueError as exc:
            raise SystemExit(f"{flag} {item!r}: {exc}") from exc
        filters[dim_id] = values
    return filters


def _parse_marginals(
    raw: list[str], *, flag: str = "--marginal"
) -> dict[str, dict[str, float]]:
    marginals: dict[str, dict[str, float]] = {}
    for item in raw:
        try:
            dim_id, weights = parse_marginal_cli(item)
        except ValueError as exc:
            raise SystemExit(f"{flag} {item!r}: {exc}") from exc
        marginals[dim_id] = weights
    return marginals


def _schema_ids() -> set[str] | None:
    catalog = REPO_ROOT / "persona" / "schema" / "dimensions.json"
    if not catalog.is_file():
        return None
    return set(load_dev_dimension_ids(catalog_path=str(catalog)))


def _remap_overlay_filter_keys(
    filters: dict[str, list[str]],
    overlay_ids: set[str],
) -> dict[str, list[str]]:
    remapped: dict[str, list[str]] = {}
    for key, values in filters.items():
        slug = key.strip().lower().replace("-", "_")
        remapped[slug if slug in overlay_ids else key] = values
    return remapped


def _remap_overlay_marginal_keys(
    marginals: dict[str, dict[str, float]],
    overlay_ids: set[str],
) -> dict[str, dict[str, float]]:
    remapped: dict[str, dict[str, float]] = {}
    for key, weights in marginals.items():
        slug = key.strip().lower().replace("-", "_")
        remapped[slug if slug in overlay_ids else key] = dict(weights)
    return remapped


def _contrast_arms_from_args(
    args: argparse.Namespace,
    overlay: list[dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    """Build contrast arms. Selected values are stamped clones; base is complementary."""
    overlay_by_id = {
        str(row["id"]): row for row in (overlay or []) if str(row.get("id") or "").strip()
    }

    def _arm(dim_id: str, extras: list[str]) -> dict[str, object] | None:
        values = [text for text in extras if str(text).strip()]
        if not values:
            return None
        slug = dim_id.strip().lower().replace("-", "_")
        dim = overlay_by_id.get(slug) or overlay_by_id.get(dim_id)
        domain: list[str] = []
        if dim is not None:
            domain = [str(v).strip() for v in (dim.get("values") or []) if str(v).strip()]
        if not domain:
            domain = [
                str(v).strip()
                for v in values_for_dimension(dim_id)
                if str(v).strip()
            ]
        base = next((v for v in domain if v not in values), None)
        if base is None:
            base = domain[0] if domain else values[0]
        return {
            "overlayId": dim_id,
            "baseValue": base,
            "values": values,
        }

    arms: list[dict[str, object]] = []
    for item in args.contrast or []:
        try:
            dim_id, values = parse_filter_cli(item)
        except ValueError as exc:
            raise SystemExit(f"--contrast {item!r}: {exc}") from exc
        arm = _arm(dim_id, values)
        if arm is not None:
            arms.append(arm)
    if args.contrast_dim and args.contrast_value is not None:
        text = str(args.contrast_value).strip()
        if not text:
            raise SystemExit("--contrast-value must not be empty")
        arm = _arm(str(args.contrast_dim).strip(), [text])
        if arm is not None:
            arms.append(arm)
    return arms


def _contrast_plan_for(
    overlay: list[dict[str, object]],
    arms: list[dict[str, object]],
) -> list[dict[str, object]]:
    if not arms:
        return []
    try:
        return normalize_generate_contrast(overlay, arms, schema_ids=_schema_ids())
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


def _unique_dataset_dir(kind_slug: str) -> Path:
    slug = _slug(kind_slug)
    base = DATASETS_DIR / f"{DEFAULT_POOL_PREFIX}-{slug}"
    if not base.exists():
        return base
    n = 2
    while True:
        candidate = DATASETS_DIR / f"{DEFAULT_POOL_PREFIX}-{slug}-{n}"
        if not candidate.exists():
            return candidate
        n += 1


def _load_pool_personas(src: Path) -> list[dict]:
    personas: list[dict] = []
    for entry in load_manifest(src, repo_root=REPO_ROOT):
        dims = entry.get("dimensions")
        if not isinstance(dims, dict):
            continue
        row: dict = {
            "persona_id": entry.get("persona_id"),
            "version": entry.get("version", "1.0"),
            "source": entry.get("source"),
            "dimensions": dict(dims),
        }
        if entry.get("pair_id"):
            row["pair_id"] = entry["pair_id"]
        personas.append(row)
    return personas


def _resolve_stamp_map(
    overlay: list[dict[str, object]],
    stamps: dict[str, str],
) -> list[dict[str, str]]:
    schema_ids = _schema_ids()
    resolved: list[dict[str, str]] = []
    for dim_id, text in stamps.items():
        dim = resolve_contrast_overlay(
            overlay,
            dim_id,
            text,
            schema_ids=schema_ids,
        )
        resolved.append(
            {
                "id": str(dim["id"]),
                "label": str(dim.get("label") or dim_id),
                "value": str(text).strip(),
            }
        )
    return resolved


def _contrast_label_from_stamps(
    stamps: dict[str, str],
    overlay: list[dict[str, object]],
) -> str:
    labels = {str(row["id"]): str(row.get("label") or row["id"]) for row in overlay}
    bits = [
        f"{labels.get(dim, dim)}={value}" for dim, value in sorted(stamps.items())
    ]
    return f"Contrast · {', '.join(bits)}" if bits else "Contrast"


def _write_contrast_clones(
    *,
    personas: list[dict],
    overlay: list[dict[str, object]],
    plan: list[dict[str, object]],
    parent_pool: str,
    out: Path | None = None,
    progress_bars: _DatasetProgressBars | None = None,
    progress_offset: int = 0,
) -> list[Path]:
    combos = contrast_stamp_combinations(plan)
    if not combos:
        return []
    if len(personas) > GENERATE_COUNT_MAX:
        raise SystemExit(
            f"Contrast copies at most {GENERATE_COUNT_MAX} personas "
            f"({parent_pool} has {len(personas)})"
        )
    schema_ids = _schema_ids()
    written: list[Path] = []
    for index, stamps in enumerate(combos):
        dataset_index = progress_offset + index
        dataset_label = _contrast_label_from_stamps(stamps, overlay)
        if progress_bars is not None:
            progress_bars.update(
                dataset_index,
                ratio=0.05,
                detail="stamping",
                label=dataset_label,
            )
        try:
            resolved = _resolve_stamp_map(overlay, stamps)
            stamp_map = {row["id"]: row["value"] for row in resolved}
            validate_contrast_stamps_against_dag(
                personas,
                stamp_map,
                schema_ids=schema_ids,
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        cloned = clone_contrast_personas(personas, stamps=stamp_map)
        slug_parts = [f"{_slug(row['id'])}-{_slug(row['value'])}" for row in resolved]
        if out is not None and len(combos) == 1:
            dest = out if out.is_absolute() else REPO_ROOT / out
        else:
            dest = _unique_dataset_dir(f"contrast-{'-'.join(slug_parts)}")
        label = ", ".join(f"{row['id']}={row['value']}" for row in resolved)
        if progress_bars is None:
            _progress(
                "contrast",
                f"[{index + 1}/{len(combos)}] {label} → "
                f"{dest.relative_to(REPO_ROOT) if dest.is_relative_to(REPO_ROOT) else dest}",
            )
        removed = _wipe_stale_personas(dest)
        if removed and progress_bars is None:
            _progress("prepare", f"Removed {removed} stale persona_*.yaml")

        def _clone_write_progress(stage: str, payload: dict) -> None:
            if progress_bars is None:
                _write_progress(stage, payload)
                return
            if stage == "write":
                done = int(payload.get("done") or 0)
                total = max(1, int(payload.get("total") or 1))
                progress_bars.update(
                    dataset_index,
                    ratio=0.15 + 0.75 * (done / total),
                    detail=f"writing {done}/{total}",
                    label=dataset_label,
                )
            elif stage == "manifest":
                progress_bars.update(
                    dataset_index,
                    ratio=0.95,
                    detail="manifest",
                    label=dataset_label,
                )

        write_persona_dataset(
            out_dir=dest,
            personas=cloned,
            repo_root=REPO_ROOT,
            kind=dest.name,
            seed=0,
            smoke_persona_id=str(cloned[0]["persona_id"]),
            overlay_dimensions=overlay or None,
            on_progress=_clone_write_progress,
            extra_manifest={
                "parent_pool": parent_pool,
                "contrast": {
                    "dimension": resolved[0]["id"],
                    "label": resolved[0]["label"],
                    "value": resolved[0]["value"],
                    "stamps": stamp_map,
                    "source_pool": parent_pool,
                },
            },
        )
        if progress_bars is not None:
            progress_bars.complete(dataset_index)
        written.append(dest)
    return written


def _run_contrast(args: argparse.Namespace) -> None:
    src = Path(args.contrast_from)
    if not src.is_absolute():
        src = REPO_ROOT / src
    if not src.is_dir():
        raise SystemExit(f"contrast source not found: {src}")
    try:
        src_rel = str(src.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        src_rel = str(src)

    overlay: list[dict[str, object]] = []
    manifest_path = src / "manifest.json"
    if manifest_path.is_file():
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        overlay = overlay_dimensions_from_manifest(payload)

    arms = _contrast_arms_from_args(args, overlay)
    if not arms:
        raise SystemExit(
            "--contrast-from requires --contrast id=v1,v2 "
            "(or --contrast-dim / --contrast-value)"
        )

    plan = _contrast_plan_for(overlay, arms)
    personas = _load_pool_personas(src)
    if not personas:
        raise SystemExit(f"{src_rel} has no persona YAML files")

    out = None
    if args.out is not None:
        out = args.out if args.out.is_absolute() else REPO_ROOT / args.out
    labels = [
        _contrast_label_from_stamps(stamps, overlay)
        for stamps in contrast_stamp_combinations(plan)
    ]
    progress_bars = _DatasetProgressBars(labels) if labels else None
    written = _write_contrast_clones(
        personas=personas,
        overlay=overlay,
        plan=plan,
        parent_pool=src_rel,
        out=out,
        progress_bars=progress_bars,
        progress_offset=0,
    )
    _progress("done", f"Wrote {len(written)} contrast dataset(s)")


def _stamp_overlay(
    personas: list[dict],
    overlay: list[dict[str, object]],
    overlay_filters: dict[str, list[str]],
    *,
    seed: int,
) -> None:
    if not overlay:
        return
    stamp_overlay_independent(personas, overlay, overlay_filters, seed=seed + 1)
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


def _print_generate_summary(
    *,
    out: Path,
    manifest: dict,
    overlay: list[dict[str, object]],
    folder_count: int,
    grounding_meta: dict[str, object] | None,
    strategy_path: Path | None,
    task: str | None,
    stratum_top_up: list[dict[str, str]] | None,
    per_cell: int | None,
) -> None:
    rel_out = out.relative_to(REPO_ROOT) if out.is_relative_to(REPO_ROOT) else out
    _progress("done", f"Wrote {manifest['count']} personas to {rel_out}")
    if folder_count > 0:
        print(f"Smoke: persona_{manifest['smoke_persona_id']}.yaml")
    print(
        f"Dimensions: {manifest.get('dimension_count', len(manifest['dimension_ids']))} fields"
    )
    if overlay:
        print(
            "Custom dimensions: "
            + ", ".join(f"{row['id']} ({row['label']})" for row in overlay)
        )
    if _is_picker_listed(out):
        print(f"Playground Dataset picker: {rel_out}")
    else:
        print(
            "Not listed in the Playground Dataset picker "
            f"(use --out persona/datasets/{DEFAULT_POOL_PREFIX}-<name>)."
        )
    if grounding_meta is not None:
        print(
            f"Filled {len(stratum_top_up or [])} grounding cells × {per_cell} "
            f"from {task}"
        )
    if strategy_path is not None:
        print(f"Filled strategy cells from {strategy_path.relative_to(REPO_ROOT)}")
        print(f'Point the task "pool" at "{rel_out}", or pick it in Playground Dataset.')


def _generate_pool_once(
    args: argparse.Namespace,
    *,
    filters: dict[str, list[str]],
    overlay: list[dict[str, object]],
    fields: list[str],
    allocation: str | None,
    per_cell: int | None,
    sample_size: int | None,
    count: int | None,
    out: Path,
    strategy_path: Path | None,
    strategy_meta: dict[str, object] | None,
    grounding_meta: dict[str, object] | None,
    stratum_top_up: list[dict[str, str]] | None,
    contrast_plan: list[dict[str, object]] | None,
    drop_overlay_contrast_axes: bool,
    marginals: dict[str, dict[str, float]] | None = None,
    progress_bars: _DatasetProgressBars | None = None,
    progress_offset: int = 0,
) -> tuple[Path, list[dict], list[dict[str, object]], dict]:
    """Sample + write one pool; optionally write contrast clones. Returns parent info."""
    overlay_ids = {str(row["id"]) for row in overlay}
    overlay_filters = fill_overlay_filters(overlay, filters) if overlay else {}
    work_fields = list(fields)
    work_allocation = allocation
    work_per_cell = per_cell
    work_sample_size = sample_size
    work_count = count
    work_marginals = dict(marginals) if marginals else None

    if contrast_plan and drop_overlay_contrast_axes:
        contrast_ids = {str(arm["id"]) for arm in contrast_plan}
        overlay_contrast_ids = contrast_ids & overlay_ids
        work_fields = [field for field in work_fields if field not in overlay_contrast_ids]
        if not work_fields:
            remaining_catalog = [key for key in filters if key not in overlay_ids]
            if not remaining_catalog:
                if not (isinstance(work_count, int) and work_count >= 1):
                    if work_per_cell:
                        work_count = work_per_cell
                    elif work_sample_size:
                        work_count = work_sample_size
                work_per_cell = None
                work_sample_size = None
                work_allocation = None
                work_marginals = None

    parent_label = "Independent"
    if contrast_plan:
        base_preview = contrast_base_stamps(contrast_plan)
        parent_label = (
            _contrast_label_from_stamps(base_preview, overlay)
            if base_preview
            else "Contrast"
        )

    def _set_parent(ratio: float, detail: str) -> None:
        if progress_bars is not None:
            progress_bars.update(
                progress_offset,
                ratio=ratio,
                detail=detail,
                label=parent_label,
            )
        else:
            _progress("sample" if ratio < 0.15 else "write", detail)

    if progress_bars is None:
        _progress(
            "prepare",
            f"Output → {out.relative_to(REPO_ROOT) if out.is_relative_to(REPO_ROOT) else out}",
        )
    _set_parent(0.02, "preparing")
    removed = _wipe_stale_personas(out)
    if removed and progress_bars is None:
        _progress("prepare", f"Removed {removed} stale persona_*.yaml")

    if args.task and stratum_top_up is not None:
        _set_parent(
            0.05,
            f"sampling grounding ({len(stratum_top_up)} × {work_per_cell})",
        )
        personas = generate_persona_pool(
            count=work_count or 0,
            seed=args.seed,
            smoke_persona_id=args.smoke_id,
            stratum_top_up=stratum_top_up,
            min_per_stratum=work_per_cell or 0,
            extra_filters={
                key: list(values)
                for key, values in filters.items()
                if key not in overlay_ids
            }
            or None,
            include_smoke=(work_count or 0) > 0,
        )
        _stamp_overlay(personas, overlay, overlay_filters, seed=args.seed)
        folder_count = work_count or 0
        resolved_overlay = overlay
    else:
        _set_parent(0.05, "sampling Full DAG")
        try:
            generated = generate_synthetic_personas(
                count=work_count,
                seed=args.seed,
                dimension_filters=filters or None,
                stratify_fields=work_fields or None,
                allocation=work_allocation,
                per_cell=work_per_cell,
                sample_size=work_sample_size,
                marginals=work_marginals,
                overlay_dimensions=overlay or None,
                catalog_path=REPO_ROOT / "persona/schema/dimensions.json",
                force_pin=strategy_path is not None,
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        personas = generated.personas
        resolved_overlay = generated.overlay
        folder_count = generated.folder_count

    if not personas:
        raise SystemExit("generation produced no personas")

    if contrast_plan:
        base_stamps = contrast_base_stamps(contrast_plan)
        if base_stamps:
            try:
                validate_contrast_stamps_against_dag(
                    personas,
                    base_stamps,
                    schema_ids=_schema_ids(),
                )
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
            apply_dimension_stamps(personas, base_stamps)
            parent_label = _contrast_label_from_stamps(base_stamps, resolved_overlay)

    _set_parent(0.12, f"sampled {len(personas)}")

    kind = (
        f"{DEFAULT_POOL_PREFIX}-strategy-{_slug(strategy_path.parent.name)}"
        if strategy_path is not None
        else f"{DEFAULT_POOL_PREFIX}-{folder_count if folder_count > 0 else len(personas)}"
    )

    def _parent_write_progress(stage: str, payload: dict) -> None:
        if progress_bars is None:
            _write_progress(stage, payload)
            return
        if stage == "write":
            done = int(payload.get("done") or 0)
            total = max(1, int(payload.get("total") or 1))
            progress_bars.update(
                progress_offset,
                ratio=0.15 + 0.75 * (done / total),
                detail=f"writing {done}/{total}",
                label=parent_label,
            )
        elif stage == "manifest":
            progress_bars.update(
                progress_offset,
                ratio=0.95,
                detail="manifest",
                label=parent_label,
            )

    if progress_bars is None:
        _progress("write", f"Writing {len(personas)} YAML files…")
    manifest = write_persona_dataset(
        out_dir=out,
        personas=personas,
        repo_root=REPO_ROOT,
        kind=kind,
        seed=args.seed,
        smoke_persona_id=args.smoke_id,
        overlay_dimensions=resolved_overlay or None,
        on_progress=_parent_write_progress,
    )
    if progress_bars is not None:
        progress_bars.complete(progress_offset)
    if strategy_meta is not None:
        manifest["stratum_top_up"] = {
            "strategy": strategy_meta,
            "count": len(personas),
        }
        (out / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n",
            encoding="utf-8",
        )
    if grounding_meta is not None:
        manifest["stratum_top_up"] = {
            "task": args.task,
            "min_per_stratum": work_per_cell,
            "strata_count": len(stratum_top_up or []),
            "grounding": grounding_meta,
        }
        (out / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n",
            encoding="utf-8",
        )

    # Avoid interleaving summary prints with in-place TTY progress bars.
    if progress_bars is None:
        _print_generate_summary(
            out=out,
            manifest=manifest,
            overlay=resolved_overlay,
            folder_count=folder_count,
            grounding_meta=grounding_meta,
            strategy_path=strategy_path,
            task=args.task,
            stratum_top_up=stratum_top_up,
            per_cell=work_per_cell,
        )

    if contrast_plan:
        try:
            parent_rel = str(out.resolve().relative_to(REPO_ROOT.resolve()))
        except ValueError:
            parent_rel = str(out)
        clones = _write_contrast_clones(
            personas=personas,
            overlay=resolved_overlay,
            plan=contrast_plan,
            parent_pool=parent_rel,
            progress_bars=progress_bars,
            progress_offset=progress_offset + 1,
        )
        if progress_bars is None:
            _progress(
                "done",
                f"Wrote {len(clones)} contrast dataset(s) from {parent_rel}",
            )

    return out, personas, resolved_overlay, manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--count",
        type=int,
        default=None,
        help=(
            f"Random: how many personas to sample (default: {GENERATE_COUNT_DEFAULT}; "
            f"max {GENERATE_COUNT_MAX}; unused when --per-cell / --sample-size / "
            "--strategy fills cells)"
        ),
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help=(
            "Output directory (default: "
            f"persona/datasets/{DEFAULT_POOL_PREFIX}-<count>, listed in "
            "the Playground Dataset picker)"
        ),
    )
    parser.add_argument("--smoke-id", default="0042")
    parser.add_argument(
        "--overlay",
        action="append",
        default=[],
        metavar="SPEC",
        help="Custom dimension: id[:label]=value,value (repeatable)",
    )
    parser.add_argument(
        "--filter",
        action="append",
        default=[],
        metavar="SPEC",
        help=(
            "Independent filters: id=value,value (repeatable). "
            "Schema dims pin the DAG; overlay dims stamp after sample."
        ),
    )
    parser.add_argument(
        "--contrast-filter",
        action="append",
        default=[],
        metavar="SPEC",
        help=(
            "Optional Contrast shared filters (who is sampled for every contrast "
            "copy). Same id=value,value form as --filter."
        ),
    )
    parser.add_argument(
        "--contrast",
        action="append",
        default=[],
        metavar="SPEC",
        help=(
            "Contrast attributes: id=v1,v2 (repeatable). One extra dataset per "
            "value combination; schema stamps are Full-DAG-validated."
        ),
    )
    parser.add_argument(
        "--stratify",
        action="append",
        default=[],
        metavar="FIELD",
        help="Grid axes for --per-cell / --sample-size (default: every --filter id)",
    )
    parser.add_argument(
        "--allocation",
        choices=("perCell", "equalTotal", "proportional", "independentMarginal"),
        default=None,
        help="Stratified allocation (default: perCell if --per-cell, else independentMarginal if --sample-size)",
    )
    parser.add_argument(
        "--per-cell",
        type=int,
        default=None,
        help="By combo: rows per filter combination (also required with --task).",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=None,
        help="By share: total rows across cells (independentMarginal / equalTotal / proportional).",
    )
    parser.add_argument(
        "--marginal",
        action="append",
        default=[],
        metavar="SPEC",
        help=(
            "Independent By-share weights: dim=v1:w1,v2:w2 (repeatable). "
            "Any positive weights; omit for equal shares. Requires --sample-size."
        ),
    )
    parser.add_argument(
        "--contrast-marginal",
        action="append",
        default=[],
        metavar="SPEC",
        help=(
            "Contrast shared By-share weights (same form as --marginal). "
            "Requires --sample-size with --contrast / --contrast-filter."
        ),
    )
    parser.add_argument(
        "--task",
        default=None,
        help="Fill grounding probe cells for this task (requires --per-cell)",
    )
    parser.add_argument(
        "--strategy",
        default=None,
        metavar="PATH",
        help=(
            "Fill this task's persona_strategy.json (filters, allocation, and "
            "declared mix / portions). Writes "
            f"persona/datasets/{DEFAULT_POOL_PREFIX}-strategy-<task>/ "
            "(listed in the Playground Dataset picker)."
        ),
    )
    parser.add_argument(
        "--contrast-from",
        default=None,
        metavar="POOL",
        help="Clone this dataset with --contrast arms (or --contrast-dim/--contrast-value)",
    )
    parser.add_argument(
        "--contrast-dim",
        default=None,
        metavar="ID",
        help="Single contrast dimension id (with --contrast-value)",
    )
    parser.add_argument(
        "--contrast-value",
        default=None,
        metavar="VALUE",
        help="Single contrast value (with --contrast-dim)",
    )
    args = parser.parse_args()

    if args.contrast_from:
        _run_contrast(args)
        return

    if args.task and args.strategy:
        raise SystemExit("Use either --task (grounding) or --strategy, not both")
    if args.count is not None and (args.count < 1 or args.count > GENERATE_COUNT_MAX):
        raise SystemExit(f"--count must be 1..{GENERATE_COUNT_MAX}")
    if args.per_cell is not None and args.per_cell < 1:
        raise SystemExit("--per-cell must be >= 1")
    if args.sample_size is not None and args.sample_size < 1:
        raise SystemExit("--sample-size must be >= 1")
    if (args.marginal or args.contrast_marginal) and args.sample_size is None:
        raise SystemExit("--marginal / --contrast-marginal require --sample-size")
    if (args.marginal or args.contrast_marginal) and args.per_cell is not None:
        raise SystemExit("--marginal / --contrast-marginal cannot be used with --per-cell")
    if (args.task or args.strategy) and (
        args.contrast or args.contrast_filter or args.contrast_dim
    ):
        raise SystemExit(
            "--contrast / --contrast-filter are not supported with --task or --strategy"
        )
    if (args.task or args.strategy) and (args.marginal or args.contrast_marginal):
        raise SystemExit(
            "--marginal / --contrast-marginal are not supported with --task or --strategy"
        )

    overlay = _parse_overlays(args.overlay)
    overlay_ids = {str(row["id"]) for row in overlay}
    independent_filters = _remap_overlay_filter_keys(
        _parse_filters(args.filter, flag="--filter"),
        overlay_ids,
    )
    contrast_shared_filters = _remap_overlay_filter_keys(
        _parse_filters(args.contrast_filter, flag="--contrast-filter"),
        overlay_ids,
    )
    independent_marginals = _remap_overlay_marginal_keys(
        _parse_marginals(args.marginal, flag="--marginal"),
        overlay_ids,
    )
    contrast_marginals = _remap_overlay_marginal_keys(
        _parse_marginals(args.contrast_marginal, flag="--contrast-marginal"),
        overlay_ids,
    )
    contrast_arms = _contrast_arms_from_args(args, overlay)
    contrast_plan = _contrast_plan_for(overlay, contrast_arms) if contrast_arms else []
    has_contrast = bool(contrast_plan)
    independent_selected = bool(independent_filters)
    # Write Independent when filters are set or there is no contrast plan.
    # Write Contrast when a plan exists (shared filters + stamped copies).
    write_independent = (not has_contrast) or independent_selected
    write_contrast_family = has_contrast

    strategy_path: Path | None = None
    strategy_meta: dict[str, object] | None = None
    grounding_meta: dict[str, object] | None = None
    stratum_top_up: list[dict[str, str]] | None = None
    fields = [
        str(field).removeprefix("dimensions.").strip()
        for field in args.stratify
        if str(field).strip()
    ]
    allocation = args.allocation
    per_cell = args.per_cell
    sample_size = args.sample_size
    count = args.count
    filters = dict(independent_filters)

    if args.strategy:
        strategy_path = _resolve_strategy_path(args.strategy)
        strategy = _load_strategy(strategy_path)
        strategy_filters = strategy.get("dimensionFilters")
        if not isinstance(strategy_filters, dict) or not strategy_filters:
            raise SystemExit(f"{strategy_path} has no dimensionFilters")
        filters = {str(key): list(values) for key, values in strategy_filters.items()}
        filters.update(independent_filters)
        sampling = strategy.get("sampling") if isinstance(strategy.get("sampling"), dict) else {}
        if not fields:
            fields = [
                str(field).removeprefix("dimensions.").strip()
                for field in (sampling.get("fields") or [])
                if str(field).strip()
            ]
        if allocation is None:
            allocation = str(sampling.get("allocation") or "").strip() or None
        if per_cell is None and isinstance(sampling.get("perCell"), int):
            per_cell = sampling.get("perCell")
        if sample_size is None and isinstance(sampling.get("sampleSize"), int):
            sample_size = sampling.get("sampleSize")
        strategy_portions = sampling.get("portions")
        if isinstance(strategy_portions, dict) and strategy_portions:
            if not independent_marginals:
                independent_marginals = {
                    str(dim): dict(weights)
                    for dim, weights in strategy_portions.items()
                    if isinstance(weights, dict)
                }
            # Same as Playground Task-plan synthesize: declared mix is exact
            # independentMarginal quotas, not population-weighted proportional.
            if allocation in {None, "proportional"}:
                allocation = "independentMarginal"
        strategy_meta = {
            "strategy_path": str(strategy_path.relative_to(REPO_ROOT)),
            "dimensionFilters": filters,
            "sampling": {
                "mode": sampling.get("mode"),
                "fields": fields,
                "allocation": allocation,
                "perCell": per_cell,
                "sampleSize": sample_size,
                "portions": strategy_portions if isinstance(strategy_portions, dict) else None,
            },
        }
        write_independent = True
        write_contrast_family = False
    elif args.task:
        if per_cell is None:
            raise SystemExit("--task requires --per-cell >= 1")
        stratum_top_up, grounding_meta = _stratum_top_up_from_task(args.task)
        count = GENERATE_COUNT_DEFAULT if count is None else count
        write_independent = True
        write_contrast_family = False
    else:
        if allocation is None:
            if per_cell is not None:
                allocation = "perCell"
            elif sample_size is not None:
                allocation = "independentMarginal"

    if not write_independent and not write_contrast_family:
        raise SystemExit("Nothing to generate: set --filter and/or --contrast")

    default_count = count if count and count > 0 else GENERATE_COUNT_DEFAULT
    if args.out is not None:
        primary_out = args.out if args.out.is_absolute() else REPO_ROOT / args.out
    elif strategy_path is not None:
        primary_out = _strategy_out_dir(_slug(strategy_path.parent.name))
    else:
        primary_out = _default_out_dir(default_count)

    progress_labels: list[str] = []
    if write_independent:
        progress_labels.append("Independent")
    if write_contrast_family:
        base_preview = contrast_base_stamps(contrast_plan)
        progress_labels.append(
            _contrast_label_from_stamps(base_preview, overlay)
            if base_preview
            else "Contrast"
        )
        for stamps in contrast_stamp_combinations(contrast_plan):
            progress_labels.append(_contrast_label_from_stamps(stamps, overlay))
    progress_bars = (
        _DatasetProgressBars(progress_labels) if progress_labels else None
    )
    progress_offset = 0

    if write_independent:
        ind_fields = list(fields)
        if (
            not ind_fields
            and (per_cell is not None or sample_size is not None)
            and independent_filters
        ):
            ind_fields = list(independent_filters)
        _generate_pool_once(
            args,
            filters=filters if (args.strategy or args.task) else independent_filters,
            overlay=overlay,
            fields=ind_fields,
            allocation=allocation,
            per_cell=per_cell,
            sample_size=sample_size,
            count=count,
            out=primary_out,
            strategy_path=strategy_path,
            strategy_meta=strategy_meta,
            grounding_meta=grounding_meta,
            stratum_top_up=stratum_top_up,
            contrast_plan=None,
            drop_overlay_contrast_axes=False,
            marginals=independent_marginals or None,
            progress_bars=progress_bars,
            progress_offset=progress_offset,
        )
        progress_offset += 1

    if write_contrast_family:
        shared = dict(contrast_shared_filters)
        contrast_fields = list(shared) if (per_cell is not None or sample_size is not None) else []
        if args.stratify:
            contrast_fields = [
                str(field).removeprefix("dimensions.").strip()
                for field in args.stratify
                if str(field).strip()
            ]
        base_stamps = contrast_base_stamps(contrast_plan)
        if args.out is not None and not write_independent:
            contrast_out = primary_out
        elif base_stamps:
            slug_parts = [
                f"{_slug(dim)}-{_slug(value)}"
                for dim, value in sorted(base_stamps.items())
            ]
            contrast_out = _unique_dataset_dir(f"contrast-{'-'.join(slug_parts)}")
        else:
            contrast_out = (
                primary_out
                if not write_independent
                else _unique_dataset_dir(str(default_count))
            )
        _generate_pool_once(
            args,
            filters=shared,
            overlay=overlay,
            fields=contrast_fields,
            allocation=allocation,
            per_cell=per_cell,
            sample_size=sample_size,
            count=count,
            out=contrast_out,
            strategy_path=None,
            strategy_meta=None,
            grounding_meta=None,
            stratum_top_up=None,
            contrast_plan=contrast_plan,
            drop_overlay_contrast_axes=True,
            marginals=contrast_marginals or None,
            progress_bars=progress_bars,
            progress_offset=progress_offset,
        )

    if progress_bars is not None:
        _progress("done", f"Wrote {len(progress_labels)} dataset(s)")


if __name__ == "__main__":
    main()
