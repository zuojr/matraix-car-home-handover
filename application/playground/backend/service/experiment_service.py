"""Experiment orchestration: design → fan-out → aggregate → analyze.

An *experiment* runs one experiment task (``experiments/tasks/<id>`` with an
``experiment.json``) across several arms. Each arm is one design **cell** (a fixed
level per factor) and maps to **one Harbor job**, because Harbor applies env at
the job level — so each cell's stimulus params ride as ``MATRIX_PARAM_*`` on its
own job. The persona cohort is sampled **once** and shared across every arm, so
comparisons are paired by ``personaId`` (within-subject, variance-reduced).

Responsibilities:

- ``preview_design`` — expand factors × design into cells (no launch).
- ``create_experiment`` — resolve the shared cohort, expand cells, launch one job
  per cell, and persist a run manifest under ``experiments/runs/<id>/``.
- ``get_experiment`` — manifest + per-cell job coverage/status.
- ``delete_experiment`` — remove the run manifest and each arm's Harbor job.
- ``get_experiment_analysis`` — align arms on the metric contract and run the
  statistical comparison (see ``experiment_analysis``).

Persona *contrast* as a factor is structured in the manifest but not yet launched
(shared-cohort is the implemented path).
"""

from __future__ import annotations

import json
import re
import shutil
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from backend.service import job_aggregation as agg
from backend.service.application_task_metadata import (
    read_instruction_meta,
    title_from_harbor_task_name,
)
from backend.service.experiment_analysis import (
    analyze_experiment,
    analyze_persona_slices,
    discover_sliceable_dimensions,
    extract_metrics,
    rank_persona_drivers,
)
from backend.service.experiment_design import expand_design
from backend.service.llm_usage_view import usage_from_trial_result
from backend.service.persona_strategy import load_persona_strategy, sampling_to_pool_kwargs
from matraix.persona_job import load_manifest

# Short-lived analysis cache: Results + Analysis + PDF often hit the same payload
# within a session. Keyed by (experiment, alpha, correction, slice opts).
_ANALYSIS_CACHE: dict[tuple[Any, ...], tuple[dict[str, Any], float]] = {}
_ANALYSIS_CACHE_TTL_S = 90.0
_ANALYSIS_CACHE_MAX = 32
_ANALYSIS_CACHE_LOCK = threading.Lock()


def _trim_analysis_cache() -> None:
    """Drop expired / overflow entries. Callers hold ``_ANALYSIS_CACHE_LOCK``."""
    now = time.monotonic()
    expired = [k for k, (_, exp) in _ANALYSIS_CACHE.items() if exp <= now]
    for k in expired:
        _ANALYSIS_CACHE.pop(k, None)
    while len(_ANALYSIS_CACHE) > _ANALYSIS_CACHE_MAX:
        # Pop an arbitrary oldest-ish key (insertion order on 3.7+).
        _ANALYSIS_CACHE.pop(next(iter(_ANALYSIS_CACHE)), None)


if TYPE_CHECKING:  # pragma: no cover - typing only
    from backend.service.harbor_job_service import HarborJobService
    from backend.service.persona_pool_service import PersonaPoolService

DEFAULT_PERSONA_POOL = "persona/datasets/matraix-persona-dev-sample"
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_EXPERIMENT_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(text: str | None) -> datetime | None:
    if not text or not isinstance(text, str):
        return None
    value = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _slug(text: str) -> str:
    return _SLUG_RE.sub("-", text.lower()).strip("-") or "exp"


def cell_arm_label(cell: dict[str, Any] | None) -> str:
    """Human arm title for Runs / experiment tables.

    Prefer the expanded ``arm`` string (``Factor=Level · …``). For a single
    ``Factor=Level`` pair, return just the level so sibling arms read as
    distinct factor values instead of ``Arm c0``.
    """
    if not isinstance(cell, dict):
        return ""
    raw = str(cell.get("arm") or "").strip()
    if not raw:
        levels = cell.get("factorLevels") or {}
        if isinstance(levels, dict):
            raw = " · ".join(str(v) for v in levels.values() if v)
    if not raw:
        return str(cell.get("cellId") or "").strip()
    eq = raw.rfind("=")
    if eq > 0 and eq < len(raw) - 1 and " · " not in raw:
        return raw[eq + 1 :].strip() or raw
    return raw


class ExperimentError(ValueError):
    """Raised for bad experiment requests (unknown task/factor, etc.)."""


class ExperimentService:
    def __init__(
        self,
        *,
        harbor: "HarborJobService",
        persona_pool: "PersonaPoolService",
        repo_root: Path,
        runs_dir: Path | None = None,
    ) -> None:
        self.harbor = harbor
        self.persona_pool = persona_pool
        self.repo_root = Path(repo_root)
        self.runs_dir = runs_dir or (self.repo_root / "experiments" / "runs")

    @classmethod
    def from_repo(cls, *, harbor: "HarborJobService", persona_pool: "PersonaPoolService") -> "ExperimentService":
        return cls(harbor=harbor, persona_pool=persona_pool, repo_root=harbor.repo_root)

    # ------------------------------------------------------------------
    # Task discovery
    # ------------------------------------------------------------------
    def _task_dir(self, task: str) -> Path:
        task_dir = (self.repo_root / task).resolve()
        try:
            task_dir.relative_to(self.repo_root.resolve())
        except ValueError as exc:  # path traversal guard
            raise ExperimentError(f"Task path escapes repo root: {task!r}") from exc
        if not task_dir.is_dir():
            raise ExperimentError(f"Experiment task not found: {task!r}")
        return task_dir

    def load_experiment_config(self, task: str) -> dict[str, Any]:
        task_dir = self._task_dir(task)
        path = task_dir / "experiment.json"
        if not path.is_file():
            raise ExperimentError(f"Missing experiment.json in {task!r}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ExperimentError(f"Invalid experiment.json in {task!r}: {exc}") from exc
        if not isinstance(data, dict) or not data.get("factors"):
            raise ExperimentError(f"experiment.json in {task!r} declares no factors")
        return data

    # ------------------------------------------------------------------
    # Design preview
    # ------------------------------------------------------------------
    def _declared_design_type(self, config: dict[str, Any]) -> str:
        declared = config.get("design")
        # Canonical: design is a string. Legacy: design is an object with .type.
        if isinstance(declared, str) and declared:
            return declared
        if isinstance(declared, dict) and declared.get("type"):
            return str(declared["type"])
        return "full_factorial"

    def _declared_selected_factors(self, config: dict[str, Any]) -> list[str] | None:
        # Canonical: top-level selectedFactors. Legacy: design.selectedFactors.
        if config.get("selectedFactors"):
            return list(config["selectedFactors"])
        declared = config.get("design")
        if isinstance(declared, dict) and declared.get("selectedFactors"):
            return list(declared["selectedFactors"])
        return None

    def _declared_axis(self, config: dict[str, Any]) -> str:
        # Canonical: compareBy (system=sut, persona=put). Legacy: design.axis.
        compare_by = str(config.get("compareBy") or "").strip().lower()
        if compare_by == "persona":
            return "put"
        if compare_by == "system":
            return "sut"
        declared = config.get("design")
        if isinstance(declared, dict) and declared.get("axis") in ("sut", "put"):
            return str(declared["axis"])
        return "sut"

    def _declared_arm_assignment(self, config: dict[str, Any]) -> str:
        """How the sampled cohort is distributed across arms. ``shared`` = same
        personas run every arm (within-subject; size is per-arm). ``split`` =
        cohort partitioned across arms (between-subject; size is the total).
        compareBy=persona is always ``split`` (a subject cannot be two attribute
        values); system defaults ``shared``."""
        if self._declared_axis(config) == "put":
            return "split"
        declared = str(config.get("armAssignment") or "").strip().lower()
        if declared in ("shared", "split"):
            return declared
        return "shared"

    def _declared_put_dimension(self, config: dict[str, Any]) -> str | None:
        # Canonical: the space=persona factor's id. Legacy: design.putDimension.
        for factor in config.get("factors") or []:
            if isinstance(factor, dict) and factor.get("id") and str(
                factor.get("space") or ""
            ).lower() == "persona":
                return str(factor["id"])
        declared = config.get("design")
        if isinstance(declared, dict) and declared.get("putDimension"):
            return str(declared["putDimension"])
        return None

    def preview_design(
        self,
        *,
        task: str,
        design_type: str | None = None,
        selected_factors: list[str] | None = None,
    ) -> dict[str, Any]:
        config = self.load_experiment_config(task)
        design_type = design_type or self._declared_design_type(config)
        if selected_factors is None:
            selected_factors = self._declared_selected_factors(config)
        design = expand_design(
            config["factors"],
            design_type=design_type,
            selected_factors=selected_factors,
            constants=config.get("constants"),
        )
        instruction = ""
        instruction_path = self._task_dir(task) / "instruction.md"
        if instruction_path.is_file():
            instruction = instruction_path.read_text(encoding="utf-8")
        return {
            "task": task,
            "appType": config.get("appType"),
            "hypothesis": config.get("hypothesis") or "",
            "axis": self._declared_axis(config),
            "compareBy": "persona" if self._declared_axis(config) == "put" else "system",
            "armAssignment": self._declared_arm_assignment(config),
            "putDimension": self._declared_put_dimension(config),
            "constants": config.get("constants") or [],
            "design": design,
            "metricContract": config.get("metricContract") or {},
            "signals": config.get("signals") or [],
            "instructionMarkdown": instruction,
        }

    def get_experiment_task(self, task: str) -> dict[str, Any]:
        """Full read-only detail for one experiment task: hypothesis, declared
        design + expanded arms, factors, metric contract, signals, and the default
        persona cohort strategy (from persona_strategy.json)."""
        config = self.load_experiment_config(task)
        preview = self.preview_design(task=task)
        task_dir = self._task_dir(task)
        strategy = load_persona_strategy(task_dir) or {}
        # Pool is a run-time choice, not part of the task cohort contract.
        cohort = {
            "pool": str(strategy.get("pool") or "") or None,
            "sources": strategy.get("sources") or [],
            "dimensionFilters": strategy.get("dimensionFilters") or {},
            "sampling": strategy.get("sampling") or {},
            "portions": strategy.get("portions")
            if isinstance(strategy.get("portions"), dict)
            else None,
        }
        app_type = config.get("appType")
        platform: str | None = None
        os_app_backend: str | None = None
        if app_type == "os-app":
            meta = self._read_task_toml(task_dir).get("metadata")
            os_key = str((meta or {}).get("os") or "").strip().lower()
            platform = os_key if os_key in ("macos", "ios", "linux") else "linux"
            os_app_backend = {"macos": "macos", "ios": "ios"}.get(platform, "docker")
        return {
            "task": task,
            "name": self._task_title(task_dir) or Path(task).name,
            "appType": app_type,
            "platform": platform,
            "osAppBackend": os_app_backend,
            "verifier": config.get("verifier"),
            "hypothesis": config.get("hypothesis") or "",
            "axis": self._declared_axis(config),
            "compareBy": "persona" if self._declared_axis(config) == "put" else "system",
            "armAssignment": self._declared_arm_assignment(config),
            "putDimension": self._declared_put_dimension(config),
            "constants": config.get("constants") or [],
            "design": preview["design"],
            "declaredDesignType": self._declared_design_type(config),
            "factors": preview["design"]["factors"],
            "personaFactors": preview["design"].get("personaFactors") or [],
            "metricContract": config.get("metricContract") or {},
            "signals": config.get("signals") or [],
            "instructionMarkdown": preview["instructionMarkdown"],
            "cohortStrategy": cohort,
        }

    # ------------------------------------------------------------------
    # Experiment task discovery
    # ------------------------------------------------------------------
    def list_experiment_tasks(self) -> list[dict[str, Any]]:
        tasks_root = self.repo_root / "experiments" / "tasks"
        if not tasks_root.is_dir():
            return []
        out: list[dict[str, Any]] = []
        for child in sorted(tasks_root.iterdir()):
            if not child.is_dir():
                continue
            config_path = child / "experiment.json"
            if not config_path.is_file():
                continue
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            task_rel = "experiments/tasks/{}".format(child.name)
            toml = self._read_task_toml(child)
            meta = toml.get("metadata") if isinstance(toml.get("metadata"), dict) else {}
            contract = (
                config.get("metricContract")
                if isinstance(config.get("metricContract"), dict)
                else {}
            )
            factors = [f for f in (config.get("factors") or []) if isinstance(f, dict)]
            out.append(
                {
                    "task": task_rel,
                    "name": self._display_task_title(child, toml),
                    "appType": config.get("appType"),
                    "hypothesis": config.get("hypothesis") or "",
                    "designType": self._declared_design_type(config),
                    "axis": self._declared_axis(config),
                    "putDimension": self._declared_put_dimension(config),
                    "factorCount": len(factors),
                    "signalCount": len(config.get("signals") or []),
                    "factorLabels": [
                        str(f.get("label") or f.get("id") or "")
                        for f in factors
                        if (f.get("label") or f.get("id"))
                        and len(f.get("levels") or []) > 1
                        and str(f.get("space") or "system").lower() != "persona"
                    ],
                    "controlLabel": self._control_level_label(factors),
                    "primaryMetrics": [
                        str(k) for k in (contract.get("primary") or []) if k
                    ],
                    "domain": str(meta["domain"]) if meta.get("domain") else None,
                    "difficulty": str(meta["difficulty"]) if meta.get("difficulty") else None,
                }
            )
        return out

    def _read_task_toml(self, task_dir: Path) -> dict[str, Any]:
        toml_path = task_dir / "task.toml"
        if not toml_path.is_file():
            return {}
        try:
            import tomllib

            data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - best effort
            return {}
        return data if isinstance(data, dict) else {}

    def _display_task_title(self, task_dir: Path, data: dict[str, Any] | None = None) -> str:
        toml = data if data is not None else self._read_task_toml(task_dir)
        task_block = toml.get("task") if isinstance(toml.get("task"), dict) else {}
        explicit = str(task_block.get("title") or "").strip()
        # ``[task].name`` is the Harbor path (experiments/…), not a display title.
        if explicit and "/" not in explicit:
            return explicit
        heading, _ = read_instruction_meta(task_dir / "instruction.md")
        if heading:
            return heading
        harbor_name = str(task_block.get("name") or task_dir.name)
        return title_from_harbor_task_name(harbor_name) or task_dir.name

    @staticmethod
    def _control_level_label(factors: list[dict[str, Any]]) -> str | None:
        """Control level label of the first varying system factor. Honors the
        canonical factor-level ``baseline`` (a level id) and the legacy per-level
        ``baseline: true``; defaults to the first level."""
        for factor in factors:
            if str(factor.get("space") or "system").lower() == "persona":
                continue
            levels = [lvl for lvl in (factor.get("levels") or []) if isinstance(lvl, dict)]
            if len(levels) <= 1:
                continue
            baseline_id = factor.get("baseline")
            chosen: dict[str, Any] | None = None
            if isinstance(baseline_id, str) and baseline_id:
                chosen = next((lvl for lvl in levels if lvl.get("id") == baseline_id), None)
            if chosen is None:
                chosen = next((lvl for lvl in levels if lvl.get("baseline") is True), None)
            if chosen is None:
                chosen = levels[0]
            label = str(chosen.get("label") or chosen.get("id") or "").strip()
            if label:
                return label
        return None

    def _task_title(self, task_dir: Path) -> str | None:
        return self._display_task_title(task_dir)

    # ------------------------------------------------------------------
    # Cohort resolution (shared across arms)
    # ------------------------------------------------------------------
    def _resolve_cohort(
        self,
        *,
        task: str,
        per_arm: int | None,
        seed: int,
    ) -> dict[str, Any]:
        task_dir = self._task_dir(task)
        strategy = load_persona_strategy(task_dir) or {}
        pool = str(strategy.get("pool") or DEFAULT_PERSONA_POOL)
        pool_kwargs = sampling_to_pool_kwargs(strategy.get("sampling"))
        # Optional UI/API override: keep strategy filters + axes, but target N
        # personas per arm. Without override, run the authored strategy as-is.
        sample_size = pool_kwargs.get("sample_size")
        per_cell = pool_kwargs.get("sample_size_per_value_group")
        allocation = pool_kwargs.get("allocation")
        portions = pool_kwargs.get("portions")
        if isinstance(per_arm, int) and per_arm >= 1:
            sample_size = per_arm
            if per_cell is not None:
                # Authored perCell size is replaced by a total of ``per_arm``.
                per_cell = None
                allocation = allocation if allocation in {"proportional", "equalTotal"} else "equalTotal"
        sampled = self.persona_pool.sample_pool(
            persona_pool=pool,
            sample_size=sample_size or per_arm or 20,
            seed=seed,
            sources=strategy.get("sources") or None,
            dimension_filters=strategy.get("dimensionFilters") or None,
            stratify_fields=pool_kwargs.get("stratify_fields"),
            sample_size_per_value_group=per_cell,
            allocation=allocation,
            portions=portions,
            task_path=task,
            include_persona_ids=True,
        )
        persona_ids = list(sampled.get("personaIds") or [])
        if not persona_ids:
            raise ExperimentError("Cohort resolution produced no personas")
        return {
            "personaPool": str(sampled.get("pool") or pool),
            "personaIds": persona_ids,
            "seed": seed,
        }

    @staticmethod
    def _split_cohort(persona_ids: list[str], k: int, seed: int) -> list[list[str]]:
        """Partition a cohort into ``k`` disjoint, size-balanced arm groups.

        Seeded shuffle + round-robin = simple randomized between-subject
        assignment with equal arm sizes (remainder spread across the first arms).
        The cohort is already stratified-sampled upstream, so a shuffled
        round-robin keeps each arm's mix unbiased in expectation.
        """
        import random

        if k <= 1:
            return [list(persona_ids)]
        ids = list(persona_ids)
        random.Random(seed).shuffle(ids)
        groups: list[list[str]] = [[] for _ in range(k)]
        for i, pid in enumerate(ids):
            groups[i % k].append(pid)
        return groups

    # ------------------------------------------------------------------
    # Create + launch
    # ------------------------------------------------------------------
    def _launch_arm(
        self,
        *,
        task: str,
        task_abs: str,
        job_name: str,
        params: dict[str, Any],
        persona_ids: list[str] | None,
        persona_pool: str,
        use_entire_pool: bool,
        seed: int,
        execution_mode: str,
        execution_plane: str | None,
        compute_family: str | None = None,
        persona_model: str | None = None,
        agent_name: str | None = None,
        cua_backend: str | None = None,
        n_concurrent_trials: int = 2,
    ) -> None:
        extra_env = {
            "MATRIX_PARAM_{}".format(str(k).upper()): str(v)
            for k, v in (params or {}).items()
        }
        extra_env["EXPERIMENTS_TASK_DIR"] = task_abs
        launch_kwargs: dict[str, Any] = {
            "task_path": task,
            "seed": seed,
            "persona_pool": persona_pool,
            "job_name": job_name,
            "execution_mode": execution_mode,
            "execution_plane": execution_plane,
            "compute_family": compute_family,
            "extra_launch_env": extra_env,
            "n_concurrent_trials": max(1, int(n_concurrent_trials or 1)),
        }
        if persona_model:
            launch_kwargs["persona_model"] = persona_model
        if agent_name:
            launch_kwargs["agent_name"] = agent_name
        if cua_backend:
            launch_kwargs["cua_backend"] = cua_backend
        if persona_ids:
            launch_kwargs["persona_ids"] = list(persona_ids)
        elif use_entire_pool:
            launch_kwargs["use_entire_pool"] = True
        self.harbor.launch(**launch_kwargs)

    def _wait_job_terminal(self, job_name: str, *, poll_s: float = 2.0) -> None:
        """Block until a Harbor launch record reaches a terminal status."""
        terminal = {"completed", "completed_with_errors", "failed", "cancelled"}
        while True:
            with self.harbor._guard:  # noqa: SLF001
                record = self.harbor._launches.get(job_name)  # noqa: SLF001
            status = getattr(record, "status", None) if record is not None else None
            if status in terminal:
                return
            time.sleep(poll_s)

    def _execution_plan(
        self,
        *,
        arm_count: int,
        n_concurrent_trials: int,
        parallel_arms: bool,
    ) -> dict[str, Any]:
        n = max(1, int(n_concurrent_trials or 1))
        arms = max(1, int(arm_count or 1))
        parallel = bool(parallel_arms)
        return {
            "nConcurrentTrials": n,
            "parallelArms": parallel,
            "armCount": arms,
            "effectiveConcurrent": n * arms if parallel else n,
        }

    def _dispatch_arm_launches(
        self,
        specs: list[dict[str, Any]],
        *,
        parallel_arms: bool,
        n_concurrent_trials: int,
    ) -> None:
        """Launch arm jobs: overlap when ``parallel_arms``, else one-after-another."""
        if not specs:
            return
        kwargs_common = {"n_concurrent_trials": n_concurrent_trials}

        if parallel_arms or len(specs) == 1:
            for spec in specs:
                self._launch_arm(**spec, **kwargs_common)
            return

        # Serial arms: start the first now (so detail has a live job), chain the rest.
        first, rest = specs[0], specs[1:]
        self._launch_arm(**first, **kwargs_common)

        def _continue() -> None:
            try:
                self._wait_job_terminal(str(first["job_name"]))
                for spec in rest:
                    self._launch_arm(**spec, **kwargs_common)
                    self._wait_job_terminal(str(spec["job_name"]))
            except Exception as exc:  # noqa: BLE001 - persist unstarted dispatch, not fake jobs
                with self.harbor._guard:  # noqa: SLF001
                    unstarted = [str(s["job_name"]) for s in rest if str(s["job_name"]) not in self.harbor._launches]  # noqa: SLF001
                    self.harbor._experiment_dispatch_errors.update({name: type(exc).__name__ for name in unstarted})  # noqa: SLF001
                exp_id = str(first["job_name"]).rsplit("-c", 1)[0]
                path = self.runs_dir / exp_id / "dispatch-error.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"source": "experiment_dispatch", "createdAt": _utc_now(), "errorType": type(exc).__name__, "notStartedJobNames": unstarted}), encoding="utf-8")

        threading.Thread(
            target=_continue,
            name="exp-serial-arms-{}".format(first.get("job_name") or "run"),
            daemon=True,
        ).start()

    def create_experiment(
        self,
        *,
        task: str,
        design_type: str | None = None,
        selected_factors: list[str] | None = None,
        per_arm: int | None = None,
        seed: int = 42,
        name: str | None = None,
        metric_contract: dict[str, Any] | None = None,
        execution_mode: str = "auto",
        execution_plane: str | None = None,
        compute_family: str | None = None,
        persona_ids: list[str] | None = None,
        persona_pool: str | None = None,
        use_entire_pool: bool = False,
        axis: str | None = None,
        put_dimension: str | None = None,
        put_arms: list[dict[str, Any]] | None = None,
        persona_model: str | None = None,
        agent_name: str | None = None,
        cua_backend: str | None = None,
        n_concurrent_trials: int = 2,
        parallel_arms: bool = True,
    ) -> dict[str, Any]:
        config = self.load_experiment_config(task)
        design_type = design_type or self._declared_design_type(config)
        if selected_factors is None:
            selected_factors = self._declared_selected_factors(config)
        design = expand_design(
            config["factors"],
            design_type=design_type,
            selected_factors=selected_factors,
            constants=config.get("constants"),
        )
        contract = metric_contract or config.get("metricContract") or {}
        axis = (axis or self._declared_axis(config)).lower()
        arm_assignment = "split" if axis == "put" else self._declared_arm_assignment(config)
        if axis == "put" and not put_dimension:
            put_dimension = self._declared_put_dimension(config)
        experiment_id = "exp-{}-{}".format(_slug(name or Path(task).name), uuid.uuid4().hex[:8])
        task_abs = str(self._task_dir(task))
        n_concurrent_trials = max(1, int(n_concurrent_trials or 1))
        parallel_arms = bool(parallel_arms)

        if axis == "put":
            cells, sampling, design_meta = self._launch_put(
                task=task,
                task_abs=task_abs,
                experiment_id=experiment_id,
                design=design,
                put_dimension=put_dimension,
                put_arms=put_arms or [],
                seed=seed,
                execution_mode=execution_mode,
                execution_plane=execution_plane,
                compute_family=compute_family,
                persona_model=persona_model,
                agent_name=agent_name,
                cua_backend=cua_backend,
                n_concurrent_trials=n_concurrent_trials,
                parallel_arms=parallel_arms,
            )
        else:
            cells, sampling, design_meta = self._launch_sut(
                task=task,
                task_abs=task_abs,
                experiment_id=experiment_id,
                design=design,
                design_type=design_type,
                selected_factors=selected_factors,
                per_arm=per_arm,
                seed=seed,
                arm_assignment=arm_assignment,
                persona_ids=persona_ids,
                persona_pool=persona_pool,
                use_entire_pool=use_entire_pool,
                execution_mode=execution_mode,
                execution_plane=execution_plane,
                compute_family=compute_family,
                persona_model=persona_model,
                agent_name=agent_name,
                cua_backend=cua_backend,
                n_concurrent_trials=n_concurrent_trials,
                parallel_arms=parallel_arms,
            )

        execution = self._execution_plan(
            arm_count=len(cells),
            n_concurrent_trials=n_concurrent_trials,
            parallel_arms=parallel_arms,
        )
        manifest = {
            "schemaVersion": "1.0",
            "experimentId": experiment_id,
            "name": name or Path(task).name,
            "task": task,
            "appType": config.get("appType"),
            "createdAt": _utc_now(),
            "status": "running",
            "axis": axis,
            "compareBy": "persona" if axis == "put" else "system",
            "armAssignment": arm_assignment,
            "personaModel": persona_model or None,
            "agentName": agent_name or None,
            "cuaBackend": cua_backend or None,
            "hypothesis": config.get("hypothesis") or "",
            "design": design_meta,
            "sampling": sampling,
            "execution": execution,
            "cohortStrategy": self._cohort_strategy_snapshot(task),
            "factors": list(config.get("factors") or []),
            "instructionMarkdown": self._task_instruction(task),
            "metricContract": contract,
            "signals": config.get("signals") or [],
            "cells": cells,
        }
        self._write_manifest(experiment_id, manifest)
        return manifest

    def _launch_sut(
        self,
        *,
        task: str,
        task_abs: str,
        experiment_id: str,
        design: dict[str, Any],
        design_type: str,
        selected_factors: list[str] | None,
        per_arm: int | None,
        seed: int,
        arm_assignment: str = "shared",
        persona_ids: list[str] | None,
        persona_pool: str | None,
        use_entire_pool: bool,
        execution_mode: str,
        execution_plane: str | None,
        compute_family: str | None = None,
        persona_model: str | None = None,
        agent_name: str | None = None,
        cua_backend: str | None = None,
        n_concurrent_trials: int = 2,
        parallel_arms: bool = True,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
        """System-under-test (SUT): arms are design cells.

        ``arm_assignment`` controls how the sampled cohort maps to arms:

        - ``shared`` — the SAME cohort runs every arm (within-subject / paired).
          Analysis pairs by personaId; the requested size is per-arm.
        - ``split`` — the cohort is partitioned into disjoint per-arm groups
          (between-subject). Each persona runs one arm; the requested size is the
          total, so each arm gets ~N/arms. Analysis falls back to unpaired since
          no personaId spans arms.
        """
        design_cells = design["cells"]
        split = str(arm_assignment or "shared").lower() == "split"
        if persona_ids or (use_entire_pool and persona_pool):
            cohort = {
                "personaPool": persona_pool or DEFAULT_PERSONA_POOL,
                "personaIds": list(persona_ids or []),
                "useEntirePool": bool(use_entire_pool),
            }
        else:
            cohort = self._resolve_cohort(task=task, per_arm=per_arm, seed=seed)
            cohort["useEntirePool"] = False

        use_entire = bool(cohort.get("useEntirePool"))
        all_ids = list(cohort["personaIds"])
        # split cannot partition an unbounded "entire pool" draw — fall back to
        # sharing that pool across arms rather than silently sending nothing.
        do_split = split and not use_entire and len(all_ids) >= len(design_cells) > 0
        arm_groups = (
            self._split_cohort(all_ids, len(design_cells), seed)
            if do_split
            else [all_ids for _ in design_cells]
        )

        cells: list[dict[str, Any]] = []
        specs: list[dict[str, Any]] = []
        for idx, cell in enumerate(design_cells):
            job_name = "{}-c{}".format(experiment_id, idx)
            group = arm_groups[idx]
            cell_out = {
                **cell,
                "jobName": job_name,
                "status": "queued",
            }
            if do_split:
                cell_out["personaCount"] = len(group)
            cells.append(cell_out)
            specs.append(
                {
                    "task": task,
                    "task_abs": task_abs,
                    "job_name": job_name,
                    "params": cell.get("params") or {},
                    "persona_ids": group,
                    "persona_pool": cohort["personaPool"],
                    "use_entire_pool": use_entire,
                    "seed": seed,
                    "execution_mode": execution_mode,
                    "execution_plane": execution_plane,
                    "compute_family": compute_family,
                    "persona_model": persona_model,
                    "agent_name": agent_name,
                    "cua_backend": cua_backend,
                }
            )
        self._dispatch_arm_launches(
            specs,
            parallel_arms=parallel_arms,
            n_concurrent_trials=n_concurrent_trials,
        )
        if do_split:
            per_arm_count = min((len(g) for g in arm_groups), default=0)
        else:
            per_arm_count = len(all_ids) or (per_arm or 0)
        sampling = {
            "perArm": per_arm_count,
            "seed": seed,
            "personaIds": all_ids,
            "personaPool": cohort["personaPool"],
            "useEntirePool": use_entire,
            "armAssignment": "split" if do_split else "shared",
        }
        design_meta = {
            "type": design_type,
            "effectiveType": design["effectiveType"],
            "sutFactors": selected_factors or [f["id"] for f in design["factors"]],
        }
        return cells, sampling, design_meta

    def _launch_put(
        self,
        *,
        task: str,
        task_abs: str,
        experiment_id: str,
        design: dict[str, Any],
        put_dimension: str | None,
        put_arms: list[dict[str, Any]],
        seed: int,
        execution_mode: str,
        execution_plane: str | None,
        compute_family: str | None = None,
        persona_model: str | None = None,
        agent_name: str | None = None,
        cua_backend: str | None = None,
        n_concurrent_trials: int = 2,
        parallel_arms: bool = True,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
        """Persona-attribute-under-test: the environment is fixed (the all-baseline
        cell) and arms are DIFFERENT persona cohorts that contrast on one attribute
        (between-subject). No identical copies."""
        if len(put_arms) < 2:
            raise ExperimentError("PUT axis requires at least two persona arms")
        baseline_cell = next(
            (c for c in design["cells"] if c.get("baseline")), design["cells"][0]
        )
        env_params = baseline_cell.get("params") or {}
        env_levels = baseline_cell.get("factorLevels") or {}
        dim = put_dimension or "persona"
        cells: list[dict[str, Any]] = []
        arm_meta: list[dict[str, Any]] = []
        specs: list[dict[str, Any]] = []
        for idx, arm in enumerate(put_arms):
            label = str(arm.get("label") or "Arm {}".format(idx + 1))
            value = arm.get("dimensionValue")
            a_ids = list(arm.get("personaIds") or [])
            a_pool = str(arm.get("personaPool") or DEFAULT_PERSONA_POOL)
            a_entire = bool(arm.get("useEntirePool"))
            if not a_ids and not a_entire:
                raise ExperimentError(f"PUT arm {label!r} has no personas")
            job_name = "{}-p{}".format(experiment_id, idx)
            cell_id = "put:{}={}".format(dim, value or _slug(label))
            cells.append(
                {
                    "cellId": cell_id,
                    "arm": label,
                    "baseline": idx == 0,
                    "factorLevels": {**env_levels, dim: value or label},
                    "params": dict(env_params),
                    "jobName": job_name,
                    "status": "queued",
                    "dimensionValue": value,
                    "personaCount": len(a_ids),
                    "personaPool": a_pool,
                    "useEntirePool": a_entire,
                }
            )
            arm_meta.append(
                {
                    "cellId": cell_id,
                    "label": label,
                    "dimensionValue": value,
                    "personaCount": len(a_ids),
                    "personaPool": a_pool,
                }
            )
            specs.append(
                {
                    "task": task,
                    "task_abs": task_abs,
                    "job_name": job_name,
                    "params": env_params,
                    "persona_ids": a_ids,
                    "persona_pool": a_pool,
                    "use_entire_pool": a_entire,
                    "seed": seed,
                    "execution_mode": execution_mode,
                    "execution_plane": execution_plane,
                    "compute_family": compute_family,
                    "persona_model": persona_model,
                    "agent_name": agent_name,
                    "cua_backend": cua_backend,
                }
            )
        self._dispatch_arm_launches(
            specs,
            parallel_arms=parallel_arms,
            n_concurrent_trials=n_concurrent_trials,
        )
        sampling = {
            "axis": "put",
            "dimension": dim,
            "seed": seed,
            "arms": arm_meta,
        }
        design_meta = {
            "type": "put",
            "effectiveType": "put",
            "sutFactors": [],
            "putDimension": dim,
            "environment": env_levels,
        }
        return cells, sampling, design_meta

    # ------------------------------------------------------------------
    # Manifest persistence
    # ------------------------------------------------------------------
    def _manifest_path(self, experiment_id: str) -> Path:
        return self.runs_dir / experiment_id / "manifest.json"

    def _write_manifest(self, experiment_id: str, manifest: dict[str, Any]) -> None:
        path = self._manifest_path(experiment_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    def _read_manifest(self, experiment_id: str) -> dict[str, Any]:
        path = self._manifest_path(experiment_id)
        if not path.is_file():
            raise ExperimentError(f"Experiment not found: {experiment_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def delete_experiment(self, experiment_id: str) -> None:
        if not _EXPERIMENT_ID_RE.match(experiment_id or ""):
            raise ExperimentError(f"Experiment not found: {experiment_id}")
        manifest = self._read_manifest(experiment_id)
        for cell in manifest.get("cells") or []:
            job_name = cell.get("jobName")
            if not job_name:
                continue
            try:
                self.harbor.delete_job(str(job_name))
            except ValueError:
                continue
        run_dir = self.runs_dir / experiment_id
        if run_dir.is_dir():
            shutil.rmtree(run_dir)

    def job_arm_index(self) -> dict[str, dict[str, Any]]:
        """Map Harbor ``jobName`` → arm display fields from run manifests.

        Used by ``GET /api/harbor/jobs`` so the Runs list can title arms by
        factor combination instead of ``Arm c0``.
        """
        if not self.runs_dir.is_dir():
            return {}
        out: dict[str, dict[str, Any]] = {}
        for child in self.runs_dir.iterdir():
            path = child / "manifest.json"
            if not path.is_file():
                continue
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            experiment_id = str(manifest.get("experimentId") or child.name)
            for cell in manifest.get("cells") or []:
                if not isinstance(cell, dict):
                    continue
                job_name = cell.get("jobName")
                if not job_name:
                    continue
                levels = cell.get("factorLevels") if isinstance(cell.get("factorLevels"), dict) else {}
                out[str(job_name)] = {
                    "experimentId": experiment_id,
                    "arm": cell.get("arm"),
                    "armLabel": cell_arm_label(cell),
                    "armBaseline": bool(cell.get("baseline")),
                    "factorLevels": levels,
                    "cellId": cell.get("cellId"),
                }
        return out

    # ------------------------------------------------------------------
    # Read / status
    # ------------------------------------------------------------------
    def list_experiments(self) -> list[dict[str, Any]]:
        if not self.runs_dir.is_dir():
            return []
        out: list[dict[str, Any]] = []
        for child in sorted(self.runs_dir.iterdir(), reverse=True):
            path = child / "manifest.json"
            if not path.is_file():
                continue
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            total = 0
            done = 0
            ready = 0
            cost_total: float | None = None
            started_min: datetime | None = None
            finished_max: datetime | None = None
            for cell in manifest.get("cells") or []:
                cov = self._cell_coverage(cell.get("jobName"))
                total += cov["trialCount"]
                done += cov["completedTrials"]
                ready += cov["artifactReadyTrials"]
                roll = self._cell_rollup(
                    cell.get("jobName"), persona_model=manifest.get("personaModel")
                )
                if roll["costUsd"] is not None:
                    cost_total = (cost_total or 0.0) + roll["costUsd"]
                started = _parse_iso(roll["startedAt"])
                finished = _parse_iso(roll["finishedAt"])
                if started and (started_min is None or started < started_min):
                    started_min = started
                if finished and (finished_max is None or finished > finished_max):
                    finished_max = finished
            duration_seconds: float | None = None
            if started_min and finished_max and finished_max >= started_min:
                duration_seconds = (finished_max - started_min).total_seconds()
            contract = manifest.get("metricContract") or {}
            metrics_count = sum(
                len(contract.get(role) or []) for role in ("primary", "secondary", "guardrail")
            )
            out.append(
                {
                    "experimentId": manifest.get("experimentId"),
                    "name": manifest.get("name"),
                    "task": manifest.get("task"),
                    "appType": manifest.get("appType"),
                    "createdAt": manifest.get("createdAt"),
                    "status": self._derive_status(total, done, ready),
                    "armCount": len(manifest.get("cells") or []),
                    "axis": manifest.get("axis"),
                    "personaModel": manifest.get("personaModel"),
                    "designType": (manifest.get("design") or {}).get("effectiveType"),
                    "hypothesis": manifest.get("hypothesis") or "",
                    "perArm": (manifest.get("sampling") or {}).get("perArm"),
                    "metricsCount": metrics_count,
                    "jobNames": [
                        cell.get("jobName")
                        for cell in (manifest.get("cells") or [])
                        if cell.get("jobName")
                    ],
                    "costUsd": cost_total,
                    "durationSeconds": duration_seconds,
                    "progress": {
                        "trialCount": total,
                        "completedTrials": done,
                        "artifactReadyTrials": ready,
                    },
                }
            )
        return out

    def _cell_coverage(self, job_name: str | None) -> dict[str, int]:
        """Cheap per-cell coverage from the directory layout only.

        ``completedTrials`` counts trials that wrote ``result.json`` (this
        includes *failed* trials, which still write a result). ``artifactReady``
        counts trials that additionally produced ``verifier/structured_output.json``
        — the signal the scorecard actually needs — so we can tell a run that
        finished-but-produced-no-data apart from a genuinely complete one.
        """
        if not job_name:
            return {"trialCount": 0, "completedTrials": 0, "artifactReadyTrials": 0}
        job_dir = self.harbor.jobs_dir / job_name
        trial_dirs = agg.iter_job_trial_dirs(job_dir)
        completed = 0
        ready = 0
        for path in trial_dirs:
            if (path / "result.json").is_file():
                completed += 1
                if (path / "verifier" / "structured_output.json").is_file():
                    ready += 1
        return {
            "trialCount": len(trial_dirs),
            "completedTrials": completed,
            "artifactReadyTrials": ready,
        }

    def _cell_rollup(self, job_name: str | None, *, persona_model: str | None = None) -> dict[str, Any]:
        """Per-cell timing + cost. Prefers Harbor job stats, then the survey
        spend file, then an estimate from per-trial token counts."""
        out: dict[str, Any] = {"costUsd": None, "startedAt": None, "finishedAt": None}
        if not job_name:
            return out
        job_dir = self.harbor.jobs_dir / job_name
        config_path = job_dir / "config.json"
        if config_path.is_file():
            config = json.loads(config_path.read_text(encoding="utf-8"))
            native_journey = any(str(a.get("import_path", "")).startswith("matraix.journeys.agent:") for a in config.get("agents", []))
        else:
            native_journey = False
        path = job_dir / "result.json"
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = None
            if isinstance(data, dict):
                stats = data.get("stats")
                if isinstance(stats, dict) and isinstance(stats.get("cost_usd"), (int, float)):
                    out["costUsd"] = float(stats["cost_usd"])
                out["startedAt"] = data.get("started_at")
                out["finishedAt"] = data.get("finished_at")
        if native_journey:
            # Harbor's agent fields contain PUT tokens; this experiment also
            # has a separate SUT. No combined cash cost has been reported.
            out["costUsd"] = None
            return out
        if out["costUsd"] is None:
            budget = job_dir / "_matraix_budget.json"
            if budget.is_file():
                try:
                    payload = json.loads(budget.read_text(encoding="utf-8"))
                    spent = payload.get("spent_usd") if isinstance(payload, dict) else None
                    if isinstance(spent, (int, float)) and spent > 0:
                        out["costUsd"] = float(spent)
                except (json.JSONDecodeError, OSError, TypeError, ValueError):
                    pass
        if out["costUsd"] is None:
            estimated = self._estimate_cell_cost(job_dir, persona_model=persona_model)
            if estimated is not None:
                out["costUsd"] = estimated
        return out

    def _estimate_cell_cost(self, job_dir: Path, *, persona_model: str | None) -> float | None:
        """Sum trial token usage and price it. Returns None if unpriceable."""
        try:
            from playground.llm_usage import estimate_completion_cost_usd
        except ImportError:
            return None
        n_in = n_out = n_cache = 0
        saw = False
        known_cost = 0.0
        known_any = False
        for trial_dir in agg.iter_job_trial_dirs(job_dir):
            result_path = trial_dir / "result.json"
            if not result_path.is_file():
                continue
            try:
                payload = json.loads(result_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            usage = usage_from_trial_result(payload)
            if not usage:
                continue
            saw = True
            if isinstance(usage.get("costUsd"), (int, float)):
                known_cost += float(usage["costUsd"])
                known_any = True
                continue
            if isinstance(usage.get("nInputTokens"), int):
                n_in += usage["nInputTokens"]
            if isinstance(usage.get("nOutputTokens"), int):
                n_out += usage["nOutputTokens"]
            if isinstance(usage.get("nCacheTokens"), int):
                n_cache += usage["nCacheTokens"]
        if not saw:
            return None
        estimated, _ = estimate_completion_cost_usd(
            model=persona_model or "",
            n_input_tokens=n_in or None,
            n_output_tokens=n_out or None,
            n_cache_tokens=n_cache or None,
        )
        total = 0.0
        have = False
        if known_any:
            total += known_cost
            have = True
        if estimated is not None:
            total += estimated
            have = True
        return total if have and total > 0 else None

    @staticmethod
    def _derive_status(total: int, done: int, ready: int) -> str:
        """Accurate run status from coverage counts.

        - no trials yet -> ``pending``
        - still finishing -> ``running``
        - all finished, none produced data -> ``failed``
        - all finished, some (not all) produced data -> ``partial``
        - all finished and all produced data -> ``complete``
        """
        if total <= 0:
            return "pending"
        if done < total:
            return "running"
        if ready <= 0:
            return "failed"
        if ready < total:
            return "partial"
        return "complete"

    def _task_instruction(self, task: str) -> str:
        path = self._task_dir(task) / "instruction.md"
        if path.is_file():
            return path.read_text(encoding="utf-8")
        return ""

    def _run_persona_ids(self, manifest: dict[str, Any]) -> tuple[list[str], str]:
        """Return (persona_ids, pool) for the shared SUT cohort (or first PUT arm)."""
        sampling = manifest.get("sampling") if isinstance(manifest.get("sampling"), dict) else {}
        pool = str(sampling.get("personaPool") or DEFAULT_PERSONA_POOL)
        ids = [str(pid) for pid in (sampling.get("personaIds") or []) if pid]
        if ids:
            return ids, pool
        # PUT: IDs are not stored on the manifest — fall back to first arm's Harbor job.
        for cell in manifest.get("cells") or []:
            job_name = cell.get("jobName")
            if not job_name:
                continue
            cell_pool = str(cell.get("personaPool") or pool)
            try:
                job = self.harbor.get_job(str(job_name))
            except Exception:  # noqa: BLE001
                continue
            trial_ids: list[str] = []
            for trial in job.get("trials") or []:
                pid = trial.get("personaId") or trial.get("persona_id")
                if pid:
                    trial_ids.append(str(pid))
            if trial_ids:
                return trial_ids, cell_pool
        return [], pool

    def _persona_dims_by_id(
        self, *, persona_pool: str, persona_ids: list[str]
    ) -> dict[str, dict[str, str]]:
        """Map persona id → dimensions for the cohort (YAML-backed when available)."""
        if not persona_ids:
            return {}
        wanted = {pid.strip() for pid in persona_ids if pid and str(pid).strip()}
        out: dict[str, dict[str, str]] = {}
        try:
            pool_dir = self.persona_pool._pool_dir(persona_pool)  # noqa: SLF001
            entries = load_manifest(pool_dir, repo_root=self.repo_root)
        except Exception:  # noqa: BLE001
            entries = []
        by_id = {
            str(e.get("persona_id") or "").strip(): e
            for e in entries
            if isinstance(e, dict) and e.get("persona_id")
        }
        for pid in wanted:
            entry = by_id.get(pid) or by_id.get(pid.zfill(4) if pid.isdigit() else pid)
            if entry is None:
                continue
            try:
                dims = self.persona_pool._yaml_dimensions(entry)  # noqa: SLF001
            except Exception:  # noqa: BLE001
                dims = {}
            if dims:
                out[pid] = dims
        return out

    def _build_cohort_mix(self, manifest: dict[str, Any]) -> dict[str, Any] | None:
        """Actual attribute mix for this run's cohort, vs the task contract.

        Used on Setup so operators can see whether a testing draw still matches
        the declared filters / stratify shares (not just n).
        """
        strategy = manifest.get("cohortStrategy") if isinstance(manifest.get("cohortStrategy"), dict) else {}
        filters = {
            str(k): [str(v) for v in (vals or []) if v is not None and str(v).strip()]
            for k, vals in (strategy.get("dimensionFilters") or {}).items()
            if isinstance(vals, (list, tuple))
        }
        sampling_block = strategy.get("sampling") if isinstance(strategy.get("sampling"), dict) else {}
        fields = [str(f) for f in (sampling_block.get("fields") or []) if f]
        portions = strategy.get("portions") if isinstance(strategy.get("portions"), dict) else None
        if portions is None and isinstance(sampling_block.get("portions"), dict):
            portions = sampling_block.get("portions")

        dim_ids: list[str] = []
        for dim in fields + list(filters.keys()):
            if dim and dim not in dim_ids:
                dim_ids.append(dim)
        if not dim_ids:
            return None

        persona_ids, pool = self._run_persona_ids(manifest)
        if not persona_ids:
            return {
                "n": 0,
                "resolved": 0,
                "missing": 0,
                "pool": pool,
                "dimensions": [],
                "vsContract": "unknown",
                "note": "No persona ids to compute mix.",
            }

        dims_by_id = self._persona_dims_by_id(persona_pool=pool, persona_ids=persona_ids)
        n = len(persona_ids)
        resolved = len(dims_by_id)
        dimensions_out: list[dict[str, Any]] = []
        overall = "match"

        for dim in dim_ids:
            allowed = filters.get(dim) or []
            counts: dict[str, int] = {}
            for dims in dims_by_id.values():
                raw = dims.get(dim)
                value = str(raw).strip() if raw is not None else ""
                if not value:
                    value = "(missing)"
                counts[value] = counts.get(value, 0) + 1
            # Include contract values with zero so gaps are visible.
            for v in allowed:
                counts.setdefault(v, 0)

            dim_portions = portions.get(dim) if isinstance(portions, dict) else None
            equal = (1.0 / len(allowed)) if allowed else None
            buckets: list[dict[str, Any]] = []
            dim_ok = True
            # Stable order: contract values first, then extras by count desc.
            ordered_values = list(allowed) + sorted(
                (v for v in counts if v not in allowed),
                key=lambda v: (-counts[v], v),
            )
            for value in ordered_values:
                count = counts.get(value, 0)
                pct = (count / resolved) if resolved else 0.0
                in_contract = value in allowed if allowed else True
                expected_pct: float | None = None
                if in_contract and allowed:
                    if isinstance(dim_portions, dict) and value in dim_portions:
                        try:
                            expected_pct = float(dim_portions[value])
                        except (TypeError, ValueError):
                            expected_pct = equal
                    else:
                        expected_pct = equal
                share_ok = True
                if expected_pct is not None and resolved > 0:
                    # Absolute share tolerance: 5pp, or 1 person for tiny draws.
                    tol = max(0.05, 1.0 / resolved)
                    share_ok = abs(pct - expected_pct) <= tol + 1e-9
                if not in_contract and count > 0:
                    dim_ok = False
                    overall = "mismatch"
                elif in_contract and expected_pct is not None and not share_ok:
                    dim_ok = False
                    if overall == "match":
                        overall = "partial"
                buckets.append(
                    {
                        "value": value,
                        "count": count,
                        "pct": round(pct, 4),
                        "expectedPct": (
                            round(expected_pct, 4) if expected_pct is not None else None
                        ),
                        "inContract": in_contract,
                        "shareOk": share_ok if expected_pct is not None else in_contract,
                    }
                )
            dimensions_out.append(
                {
                    "id": dim,
                    "stratify": dim in fields,
                    "match": "match" if dim_ok else "mismatch",
                    "buckets": buckets,
                }
            )
            if not dim_ok and overall == "match":
                overall = "mismatch"

        if resolved < n and overall == "match":
            overall = "partial"

        return {
            "n": n,
            "resolved": resolved,
            "missing": max(0, n - resolved),
            "pool": pool,
            "dimensions": dimensions_out,
            "vsContract": overall,
        }

    def _cohort_strategy_snapshot(self, task: str) -> dict[str, Any]:
        """Declared persona cohort contract from the task's persona_strategy.json.

        Defines *who* (filters / stratify / optional portions) — not *which dataset*.
        Dataset / pool is chosen at run time. ``portions`` is optional
        ``{dimension: {value: weight}}``; when omitted, selected values are equal /
        uniform (``equalTotal`` / ``perCell``) or pool-proportional (``proportional``).
        """
        strategy = load_persona_strategy(self._task_dir(task)) or {}
        sampling = strategy.get("sampling") if isinstance(strategy.get("sampling"), dict) else {}
        portions = strategy.get("portions")
        if not isinstance(portions, dict):
            portions = (sampling or {}).get("portions") if isinstance(sampling, dict) else None
        if not isinstance(portions, dict):
            portions = None
        pool = str(strategy.get("pool") or "").strip() or None
        return {
            "pool": pool,
            "sources": list(strategy.get("sources") or []),
            "dimensionFilters": dict(strategy.get("dimensionFilters") or {}),
            "sampling": dict(sampling or {}),
            "portions": portions,
        }

    def get_experiment(self, experiment_id: str) -> dict[str, Any]:
        manifest = self._read_manifest(experiment_id)
        dispatch_path = self.runs_dir / experiment_id / "dispatch-error.json"
        dispatch_error = json.loads(dispatch_path.read_text(encoding="utf-8")) if dispatch_path.is_file() else None
        total = 0
        done = 0
        ready = 0
        cost_total: float | None = None
        started_min: datetime | None = None
        finished_max: datetime | None = None
        for cell in manifest.get("cells") or []:
            cov = self._cell_coverage(cell.get("jobName"))
            roll = self._cell_rollup(
                cell.get("jobName"), persona_model=manifest.get("personaModel")
            )
            cell["coverage"] = {
                **cov,
                "costUsd": roll.get("costUsd"),
                "startedAt": roll.get("startedAt"),
                "finishedAt": roll.get("finishedAt"),
            }
            total += cov["trialCount"]
            done += cov["completedTrials"]
            ready += cov["artifactReadyTrials"]
            cell["status"] = self._derive_status(
                cov["trialCount"], cov["completedTrials"], cov["artifactReadyTrials"]
            )
            if roll.get("costUsd") is not None:
                cost_total = (cost_total or 0.0) + float(roll["costUsd"])
            started = _parse_iso(roll.get("startedAt"))
            finished = _parse_iso(roll.get("finishedAt"))
            if started and (started_min is None or started < started_min):
                started_min = started
            if finished and (finished_max is None or finished > finished_max):
                finished_max = finished
        manifest["status"] = self._derive_status(total, done, ready)
        if dispatch_error:
            manifest["dispatchError"] = dispatch_error
            manifest["status"] = "failed"
            for cell in manifest.get("cells") or []:
                if cell.get("jobName") in dispatch_error["notStartedJobNames"]:
                    cell["status"] = "not_started"
        manifest["progress"] = {
            "trialCount": total,
            "completedTrials": done,
            "artifactReadyTrials": ready,
        }
        manifest["costUsd"] = cost_total
        if started_min and finished_max and finished_max >= started_min:
            manifest["durationSeconds"] = (finished_max - started_min).total_seconds()
        else:
            manifest["durationSeconds"] = None

        if not isinstance(manifest.get("cohortStrategy"), dict):
            task = str(manifest.get("task") or "")
            if task:
                try:
                    manifest["cohortStrategy"] = self._cohort_strategy_snapshot(task)
                except Exception:  # noqa: BLE001 - best effort for older runs
                    manifest["cohortStrategy"] = None
        if not isinstance(manifest.get("factors"), list) or not manifest.get("factors"):
            task = str(manifest.get("task") or "")
            if task:
                try:
                    config = self.load_experiment_config(task)
                    factors = config.get("factors")
                    if isinstance(factors, list):
                        manifest["factors"] = factors
                except Exception:  # noqa: BLE001
                    manifest["factors"] = []
        if not str(manifest.get("instructionMarkdown") or "").strip():
            task = str(manifest.get("task") or "")
            if task:
                try:
                    manifest["instructionMarkdown"] = self._task_instruction(task)
                except Exception:  # noqa: BLE001
                    manifest["instructionMarkdown"] = ""
        try:
            manifest["cohortMix"] = self._build_cohort_mix(manifest)
        except Exception:  # noqa: BLE001 - never block detail view
            manifest["cohortMix"] = None
        return manifest

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------
    def _read_pair_id(self, trial_dir: Path) -> str | None:
        persona_rel = agg._trial_persona_path(trial_dir)
        if not persona_rel:
            return None
        persona_path = (self.repo_root / persona_rel).resolve()
        if not persona_path.is_file():
            return None
        try:
            import yaml  # local import; backend has pyyaml

            data = yaml.safe_load(persona_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - best effort
            return None
        if isinstance(data, dict) and data.get("pair_id"):
            return str(data["pair_id"])
        return None

    def _read_persona_bundle(self, trial_dir: Path) -> tuple[str | None, dict[str, Any]]:
        """One YAML read → (pairId, dimensions). Avoids double-parsing persona.yaml."""
        persona_rel = agg._trial_persona_path(trial_dir)
        if not persona_rel:
            return None, {}
        persona_path = (self.repo_root / persona_rel).resolve()
        if not persona_path.is_file():
            return None, {}
        try:
            import yaml

            data = yaml.safe_load(persona_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - best effort
            return None, {}
        if not isinstance(data, dict):
            return None, {}
        pair_id = str(data["pair_id"]) if data.get("pair_id") else None
        raw_dims = data.get("dimensions")
        dimensions: dict[str, Any] = {}
        if isinstance(raw_dims, dict):
            dimensions = {str(k): v for k, v in raw_dims.items() if v is not None}
        return pair_id, dimensions

    def _arm_trials(
        self,
        job_name: str | None,
        wanted: list[str],
        *,
        include_dimensions: bool = False,
    ) -> list[dict[str, Any]]:
        trials: list[dict[str, Any]] = []
        if not job_name:
            return trials
        job_dir = self.harbor.jobs_dir / job_name
        trial_dirs = list(agg.iter_job_trial_dirs(job_dir))
        if not trial_dirs:
            return trials

        def _one(trial_dir: Path) -> dict[str, Any] | None:
            so_path = agg.trial_evaluation_artifact_path(trial_dir)
            if not so_path.is_file():
                return None
            try:
                structured = json.loads(so_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return None
            # Fold the host-generated self-report (user_feedback.json) into the
            # evaluation. The in-container verifier runs before the post-run
            # self-report exists, so its structured_output.json omits the
            # user_feedback context; without this, self-report metrics
            # (overall_experience_rating / effort_rating / trust_level) never
            # reach the scorecard. Mirrors the Playground job-aggregation path.
            structured = agg._enrich_trial_evaluation_with_user_feedback(  # noqa: SLF001
                structured,
                trial_dir=trial_dir,
                repo_root=self.repo_root,
            )
            # Scorecard path: skip persona YAML. Shared-cohort SUT arms pair on
            # personaId (from config.json); YAML pair_id / dimensions are only
            # needed for Analysis slices. Parsing ~40KB YAML × hundreds of
            # trials was dominating Results "Computing…" latency.
            pair_id: str | None = None
            dimensions: dict[str, Any] = {}
            if include_dimensions:
                pair_id, dimensions = self._read_persona_bundle(trial_dir)
            row: dict[str, Any] = {
                "personaId": agg._trial_persona_id(trial_dir),
                "pairId": pair_id,
                "metrics": extract_metrics(structured, wanted),
            }
            if include_dimensions:
                row["dimensions"] = dimensions
            return row

        # Parallelize disk I/O for large jobs (hundreds of trials).
        if len(trial_dirs) > 24:
            from concurrent.futures import ThreadPoolExecutor

            workers = min(16, max(4, (len(trial_dirs) + 15) // 16))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for row in pool.map(_one, trial_dirs):
                    if row is not None:
                        trials.append(row)
            return trials

        for trial_dir in trial_dirs:
            row = _one(trial_dir)
            if row is not None:
                trials.append(row)
        return trials

    def get_experiment_analysis(
        self,
        experiment_id: str,
        *,
        alpha: float = 0.05,
        multiple_testing: str = "none",
        slice_dimension: str | None = None,
        slice_metric: str | None = None,
        include_slices: bool = False,
    ) -> dict[str, Any]:
        cache_key = (
            experiment_id,
            round(float(alpha), 6),
            str(multiple_testing),
            bool(include_slices),
            slice_dimension or "",
            slice_metric or "",
        )
        with _ANALYSIS_CACHE_LOCK:
            cached = _ANALYSIS_CACHE.get(cache_key)
            if cached is not None:
                payload, expires = cached
                if time.monotonic() < expires:
                    return json.loads(json.dumps(payload))

        manifest = self._read_manifest(experiment_id)
        contract = manifest.get("metricContract") or {}
        wanted = sorted({k for role in ("primary", "secondary", "guardrail") for k in (contract.get(role) or [])})
        kinds = {
            s["key"]: s["kind"]
            for s in (manifest.get("signals") or [])
            if isinstance(s, dict) and s.get("key") and s.get("kind")
        }
        # Persona YAML + slice work only when Analysis asks for it (or explicit dim).
        want_slices = bool(include_slices or slice_dimension or slice_metric)
        arms = []
        for cell in manifest.get("cells") or []:
            arms.append(
                {
                    "cellId": cell.get("cellId"),
                    "arm": cell.get("arm"),
                    "baseline": bool(cell.get("baseline")),
                    "trials": self._arm_trials(
                        cell.get("jobName"),
                        wanted,
                        include_dimensions=want_slices,
                    ),
                }
            )
        analysis = analyze_experiment(
            arms,
            contract,
            metric_kinds=kinds,
            alpha=alpha,
            multiple_testing=multiple_testing,
        )
        analysis["experimentId"] = experiment_id
        analysis["metricContract"] = contract
        analysis["armSizes"] = {a["cellId"]: len(a["trials"]) for a in arms}

        if not want_slices:
            analysis["sliceableDimensions"] = []
            analysis["slices"] = None
            analysis["sliceDrivers"] = []
            with _ANALYSIS_CACHE_LOCK:
                _ANALYSIS_CACHE[cache_key] = (analysis, time.monotonic() + _ANALYSIS_CACHE_TTL_S)
                _trim_analysis_cache()
            return analysis

        sliceable = discover_sliceable_dimensions(arms)
        analysis["sliceableDimensions"] = sliceable

        primary = (contract.get("primary") or [None])[0]
        metric = (slice_metric or primary or (wanted[0] if wanted else None)) or None
        if metric:
            analysis["sliceDrivers"] = rank_persona_drivers(
                arms,
                contract,
                metric_key=metric,
                candidate_dimensions=[d["id"] for d in sliceable],
                metric_kinds=kinds,
                alpha=alpha,
            )
        else:
            analysis["sliceDrivers"] = []

        # Default detail table to the top driver (why-first), else first sliceable.
        top_driver = (analysis["sliceDrivers"] or [None])[0]
        dim = (
            slice_dimension
            or (top_driver["dimension"] if top_driver else None)
            or (sliceable[0]["id"] if sliceable else None)
        )
        if dim and metric:
            analysis["slices"] = analyze_persona_slices(
                arms,
                contract,
                dimension=dim,
                metric_key=metric,
                metric_kinds=kinds,
                alpha=alpha,
            )
        else:
            analysis["slices"] = None
        with _ANALYSIS_CACHE_LOCK:
            _ANALYSIS_CACHE[cache_key] = (analysis, time.monotonic() + _ANALYSIS_CACHE_TTL_S)
            _trim_analysis_cache()
        return analysis
