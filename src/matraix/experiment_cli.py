"""``matraix experiment`` — headless parity for the Playground Experiments UI.

Reuses the Playground service layer (``ExperimentService`` +
``experiment_analysis``) so scripting / CI can list, launch, inspect, and
analyze factorial experiments without the web app. The ``analyze`` CSV columns
match the UI's ``experimentExport.ts`` export byte-for-byte.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager, redirect_stdout
import csv
from functools import wraps
import io
import json
import os
import sys
from pathlib import Path
from typing import Any, TextIO

from matraix.launch_env import find_repo_root, merge_pythonpath, required_pythonpath_entries

# CSV columns shared with the frontend experiment export (keep in sync with
# application/playground/frontend/src/lib/experimentExport.ts).
_CSV_COLUMNS = [
    "experiment_id",
    "experiment_name",
    "task",
    "axis",
    "metric_key",
    "role",
    "kind",
    "arm",
    "cell_id",
    "baseline_arm",
    "baseline_cell",
    "test",
    "paired",
    "n_baseline",
    "n_treatment",
    "baseline_mean",
    "treatment_mean",
    "diff",
    "delta_pct",
    "effect_type",
    "effect_size",
    "ci_low",
    "ci_high",
    "p_value",
    "p_value_adj",
    "significant",
    "reason",
    "categories",
    "treatment_distribution",
]


def _prepare_paths(repo_root: Path) -> None:
    """Put the Playground backend + MatrAIx packages on ``sys.path``.

    The experiment services live in ``application/playground`` and import as the
    top-level ``backend`` package, so that directory must be importable too.
    """
    entries = [str(repo_root / "application" / "playground")]
    entries.extend(required_pythonpath_entries(repo_root))
    for entry in reversed(entries):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    import os

    os.environ["PYTHONPATH"] = merge_pythonpath(os.environ.get("PYTHONPATH"), repo_root)


def _build_service(repo_root: Path):
    _prepare_paths(repo_root)
    from backend.service.experiment_service import ExperimentService
    from backend.service.harbor_job_service import HarborJobService
    from backend.service.persona_pool_service import PersonaPoolService

    harbor = HarborJobService.from_repo(repo_root=repo_root)
    persona_pool = PersonaPoolService.from_repo(repo_root=harbor.repo_root)
    return ExperimentService.from_repo(harbor=harbor, persona_pool=persona_pool)


def _repo_root(args: argparse.Namespace) -> Path:
    if getattr(args, "repo_root", None):
        return Path(args.repo_root).resolve()
    return find_repo_root(Path.cwd())


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def _fmt_num(value: Any, digits: int = 3) -> str:
    if isinstance(value, bool) or value is None:
        return "—" if value is None else str(value)
    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}".rstrip("0").rstrip(".") if isinstance(value, float) else str(value)
    return str(value)


def _format_list_text(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No experiments found under experiments/runs.\n"
    lines = [f"{len(rows)} experiment(s):", ""]
    for r in rows:
        prog = r.get("progress") or {}
        done = prog.get("completedTrials", 0)
        total = prog.get("trialCount", 0)
        cost = r.get("costUsd")
        cost_s = f"${cost:.3f}" if isinstance(cost, (int, float)) else "—"
        lines.append(
            f"  {r.get('experimentId')}  [{r.get('status')}]  "
            f"{(r.get('axis') or '').upper()}/{r.get('designType') or '—'}  "
            f"arms={r.get('armCount')}  trials={done}/{total}  cost={cost_s}"
        )
        name = (r.get("name") or "").strip()
        if name:
            lines.append(f"      {name}  ·  {r.get('task')}")
        else:
            lines.append(f"      {r.get('task')}")
    return "\n".join(lines) + "\n"


def _analysis_rows(
    manifest: dict[str, Any], analysis: dict[str, Any]
) -> list[dict[str, Any]]:
    baseline_arm = analysis.get("baselineArm") or ""
    baseline_cell = analysis.get("baselineCell") or ""
    out: list[dict[str, Any]] = []
    for cmp in analysis.get("comparisons") or []:
        effect = cmp.get("effect") or {}
        if isinstance(effect.get("cohensD"), (int, float)):
            effect_type, effect_size = "cohens_d", effect.get("cohensD")
        elif isinstance(effect.get("cramersV"), (int, float)):
            effect_type, effect_size = "cramers_v", effect.get("cramersV")
        elif isinstance(effect.get("deltaPct"), (int, float)):
            effect_type, effect_size = "delta_pct", effect.get("deltaPct")
        else:
            effect_type, effect_size = "", ""
        ci = effect.get("ciPct") or effect.get("ci")
        baseline = cmp.get("baseline") or {}
        treatment = cmp.get("treatment") or {}
        cats = cmp.get("categories") or []
        dist = treatment.get("distribution")
        out.append(
            {
                "experiment_id": manifest.get("experimentId"),
                "experiment_name": manifest.get("name") or "",
                "task": manifest.get("task"),
                "axis": manifest.get("axis") or "",
                "metric_key": cmp.get("metricKey"),
                "role": cmp.get("role"),
                "kind": cmp.get("kind"),
                "arm": cmp.get("arm") or cmp.get("cellId"),
                "cell_id": cmp.get("cellId"),
                "baseline_arm": baseline_arm,
                "baseline_cell": baseline_cell,
                "test": cmp.get("test") or "",
                "paired": cmp.get("paired") if cmp.get("paired") is not None else "",
                "n_baseline": baseline.get("n", ""),
                "n_treatment": treatment.get("n", ""),
                "baseline_mean": baseline.get("mean", ""),
                "treatment_mean": treatment.get("mean", ""),
                "diff": effect.get("diff", ""),
                "delta_pct": effect.get("deltaPct", ""),
                "effect_type": effect_type,
                "effect_size": effect_size,
                "ci_low": ci[0] if ci else "",
                "ci_high": ci[1] if ci else "",
                "p_value": cmp.get("pValue", "") if cmp.get("pValue") is not None else "",
                "p_value_adj": cmp.get("pValueAdj", "") if cmp.get("pValueAdj") is not None else "",
                "significant": "true" if cmp.get("significant") else "false",
                "reason": cmp.get("reason") or "",
                "categories": "|".join(str(c) for c in cats) if cats else "",
                "treatment_distribution": json.dumps(dist, separators=(",", ":")) if dist else "",
            }
        )
    return out


def _format_analysis_csv(manifest: dict[str, Any], analysis: dict[str, Any]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in _analysis_rows(manifest, analysis):
        writer.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in _CSV_COLUMNS})
    return buf.getvalue()


def _format_analysis_text(manifest: dict[str, Any], analysis: dict[str, Any]) -> str:
    correction = analysis.get("correction") or {}
    sizes = analysis.get("armSizes") or {}
    lines = [
        f"Experiment: {manifest.get('experimentId')}",
        f"  task     : {manifest.get('task')}",
        f"  axis     : {(manifest.get('axis') or '').upper()}",
        f"  baseline : {analysis.get('baselineArm') or analysis.get('baselineCell') or '—'}",
        f"  arms     : {len(sizes)}  ({', '.join(f'{k}={v}' for k, v in sizes.items())})",
        f"  correction: {correction.get('method', 'none')} · alpha={correction.get('alpha')} · {correction.get('count', 0)} tests",
        "",
    ]
    comparisons = analysis.get("comparisons") or []
    if not comparisons:
        lines.append("  (no comparisons yet — trials have not produced metrics)")
        return "\n".join(lines) + "\n"

    header = f"  {'metric':<26} {'arm':<18} {'test':<12} {'effect':>10} {'delta%':>9} {'p(adj)':>9}  sig"
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))
    for cmp in comparisons:
        effect = cmp.get("effect") or {}
        if isinstance(effect.get("cohensD"), (int, float)):
            eff = f"d={effect['cohensD']:.2f}"
        elif isinstance(effect.get("cramersV"), (int, float)):
            eff = f"V={effect['cramersV']:.2f}"
        elif isinstance(effect.get("deltaPct"), (int, float)):
            eff = f"{effect['deltaPct']:+.1f}%"
        else:
            eff = "—"
        delta = effect.get("deltaPct")
        delta_s = f"{delta:+.1f}" if isinstance(delta, (int, float)) else "—"
        p_adj = cmp.get("pValueAdj")
        if isinstance(p_adj, (int, float)):
            p_s = "<0.001" if p_adj < 0.001 else f"{p_adj:.3f}"
        else:
            p_s = "—"
        sig = "✓" if cmp.get("significant") else "·"
        metric = str(cmp.get("metricKey") or "")[:26]
        arm = str(cmp.get("arm") or cmp.get("cellId") or "")[:18]
        test = str(cmp.get("test") or cmp.get("kind") or "")[:12]
        lines.append(f"  {metric:<26} {arm:<18} {test:<12} {eff:>10} {delta_s:>9} {p_s:>9}  {sig}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

@contextmanager
def _diagnostics_on_stderr():
    """Reserve stdout for a payload, including when workers spawn Harbor.

    redirect_stdout alone cannot route inherited child-process descriptors or
    logging handlers bound before entry. Duplicate the payload descriptor first,
    then route both Python stdout and the process stdout to stderr until workers
    have drained. This is CLI-only process-global state, not a server API.
    """
    original = sys.stdout
    original.flush()
    sys.stderr.flush()
    try:
        out_fd, err_fd = original.fileno(), sys.stderr.fileno()
    except (AttributeError, io.UnsupportedOperation):
        # Embedded callers may supply StringIO; no OS stdout exists to redirect.
        with redirect_stdout(sys.stderr):
            yield original
        return

    saved_fd = os.dup(out_fd)
    payload = os.fdopen(
        saved_fd, "w", encoding=original.encoding or "utf-8",
        errors=original.errors or "strict", closefd=True,
    )
    kernel32 = None
    old_handle = None
    same_handle = False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        import msvcrt

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
        kernel32.GetStdHandle.restype = wintypes.HANDLE
        kernel32.SetStdHandle.argtypes = [wintypes.DWORD, wintypes.HANDLE]
        kernel32.SetStdHandle.restype = wintypes.BOOL
        old_handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        same_handle = old_handle == msvcrt.get_osfhandle(out_fd)

    try:
        os.dup2(err_fd, out_fd)
        if kernel32 is not None:
            # Windows Popen inherits Win32 standard handles, not CRT fd 1.
            if not kernel32.SetStdHandle(-11, msvcrt.get_osfhandle(out_fd)):
                raise ctypes.WinError(ctypes.get_last_error())
        with redirect_stdout(sys.stderr):
            yield payload
    finally:
        try:
            sys.stderr.flush()
            original.flush()
            payload.flush()
        finally:
            os.dup2(saved_fd, out_fd)
            if kernel32 is not None:
                restored = msvcrt.get_osfhandle(out_fd) if same_handle else old_handle
                kernel32.SetStdHandle(-11, restored)
            payload.close()


def _with_output_stream(handler):
    @wraps(handler)
    def run(args):
        formats = {part.strip() for part in (args.format or "text").split(",")}
        if formats & {"json", "csv", "pdf"}:
            with _diagnostics_on_stderr() as output:
                return handler(args, output=output)
        return handler(args, output=sys.stdout)

    return run


@_with_output_stream
def _cmd_list(args: argparse.Namespace, *, output: TextIO) -> None:
    svc = _build_service(_repo_root(args))
    rows = svc.list_experiments()
    if args.format == "json":
        output.write(json.dumps(rows, indent=2) + "\n")
    else:
        output.write(_format_list_text(rows))


@_with_output_stream
def _cmd_show(args: argparse.Namespace, *, output: TextIO) -> None:
    svc = _build_service(_repo_root(args))
    try:
        manifest = svc.get_experiment(args.experiment_id)
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"matraix experiment show: {exc}")
    if args.format == "json":
        output.write(json.dumps(manifest, indent=2) + "\n")
        return
    prog = manifest.get("progress") or {}
    lines = [
        f"Experiment: {manifest.get('experimentId')}",
        f"  name    : {manifest.get('name') or '—'}",
        f"  task    : {manifest.get('task')}",
        f"  axis    : {(manifest.get('axis') or '').upper()}",
        f"  status  : {manifest.get('status')}",
        f"  design  : {(manifest.get('design') or {}).get('effectiveType') or '—'}",
        f"  model   : {manifest.get('personaModel') or '—'}",
        f"  trials  : {prog.get('completedTrials', 0)}/{prog.get('trialCount', 0)}",
        f"  cost    : {('$%.3f' % manifest['costUsd']) if isinstance(manifest.get('costUsd'), (int, float)) else '—'}",
    ]
    for cell in manifest.get("cells") or []:
        lines.append(
            f"    arm {cell.get('cellId')}: {cell.get('arm') or '—'} "
            f"[{cell.get('status', '—')}] job={cell.get('jobName')}"
        )
    output.write("\n".join(lines) + "\n")


@_with_output_stream
def _cmd_analyze(args: argparse.Namespace, *, output: TextIO) -> None:
    svc = _build_service(_repo_root(args))
    alpha = 1.0 - float(args.confidence)
    if not (0.0 < alpha < 1.0):
        sys.exit("matraix experiment analyze: --confidence must be in (0, 1)")
    try:
        manifest = svc.get_experiment(args.experiment_id)
        analysis = svc.get_experiment_analysis(
            args.experiment_id,
            alpha=alpha,
            multiple_testing="bh" if args.fdr else "none",
            include_slices=bool(args.slices),
        )
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"matraix experiment analyze: {exc}")

    writers = {
        "text": lambda: _format_analysis_text(manifest, analysis),
        "json": lambda: json.dumps(analysis, indent=2) + "\n",
        "csv": lambda: _format_analysis_csv(manifest, analysis),
    }
    def pdf_bytes():
        from backend.service.report_pdf import build_experiment_report_pdf
        return build_experiment_report_pdf(manifest=manifest, analysis=analysis)

    writers["pdf"] = pdf_bytes
    formats = [f.strip() for f in (args.format or "text").split(",") if f.strip()]
    for fmt in formats:
        if fmt not in writers:
            sys.exit(f"matraix experiment analyze: unknown format {fmt!r} (use text,json,csv,pdf)")

    if "pdf" in formats and not args.output:
        sys.exit("matraix experiment analyze: PDF requires --output")

    if args.output:
        out_path = Path(args.output).expanduser().resolve()
        if len(formats) == 1:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            value = writers[formats[0]]()
            if isinstance(value, bytes):
                out_path.write_bytes(value)
            else:
                out_path.write_text(value, encoding="utf-8")
            print(f"matraix experiment analyze: wrote {out_path}", file=sys.stderr)
            return
        out_path.mkdir(parents=True, exist_ok=True)
        for fmt in formats:
            suffix = {"text": "txt", "json": "json", "csv": "csv", "pdf": "pdf"}[fmt]
            target = out_path / f"{args.experiment_id}.analysis.{suffix}"
            value = writers[fmt]()
            if isinstance(value, bytes):
                target.write_bytes(value)
            else:
                target.write_text(value, encoding="utf-8")
            print(f"matraix experiment analyze: wrote {target}", file=sys.stderr)
        return

    for i, fmt in enumerate(formats):
        if len(formats) > 1:
            print(f"===== {fmt} =====", file=output)
        output.write(writers[fmt]())


def _harbor_job_names(manifest: dict[str, Any] | None, harbor: Any) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for cell in (manifest or {}).get("cells") or []:
        job_name = str(cell.get("jobName") or "").strip()
        if job_name and job_name not in seen:
            seen.add(job_name)
            names.append(job_name)
    launches = getattr(harbor, "_launches", None)
    if isinstance(launches, dict):
        for job_name in launches:
            key = str(job_name).strip()
            if key and key not in seen:
                seen.add(key)
                names.append(key)
    return names


def _wait_experiment_jobs(harbor: Any, job_names: list[str]) -> bool:
    """Block until each arm job is terminal. Return True if any arm failed."""
    from matraix.job_run import wait_for_harbor_job

    if harbor is None or not job_names:
        return False
    failed = False
    for job_name in job_names:
        print(f"matraix experiment create: waiting for job {job_name}", file=sys.stderr)
        detail = wait_for_harbor_job(harbor, job_name)
        if isinstance(detail, dict) and detail.get("dispatch", {}).get("status") == "not_started":
            print(f"matraix experiment create: {job_name} was not started after dispatch failed", file=sys.stderr)
            failed = True
            continue
        launch = detail.get("launch") if isinstance(detail, dict) else None
        status = launch.get("status") if isinstance(launch, dict) else "unknown"
        error = launch.get("error") if isinstance(launch, dict) else None
        print(f"matraix experiment create: {job_name} status={status}", file=sys.stderr)
        if error:
            print(f"matraix experiment create: {job_name}: {error}", file=sys.stderr)
        if status in {"failed", "completed_with_errors", "cancelled"}:
            failed = True
    return failed


def _shutdown_harbor(svc: Any) -> None:
    harbor = getattr(svc, "harbor", None)
    shutdown = getattr(harbor, "shutdown", None)
    if callable(shutdown):
        shutdown()


@_with_output_stream
def _cmd_create(args: argparse.Namespace, *, output: TextIO) -> None:
    svc = _build_service(_repo_root(args))
    manifest: dict[str, Any] | None = None
    try:
        try:
            manifest = svc.create_experiment(
                task=args.task,
                name=args.name,
                per_arm=args.per_arm,
                seed=args.seed,
                execution_mode=args.mode,
                axis=args.axis,
                persona_model=args.persona_model,
                agent_name=args.agent_name,
                cua_backend=args.cua_backend,
                n_concurrent_trials=args.concurrent,
                persona_pool=getattr(args, "persona_pool", None),
                persona_ids=getattr(args, "persona_ids", None),
                parallel_arms=getattr(args, "parallel_arms", True),
            )
        except Exception as exc:  # noqa: BLE001
            harbor = getattr(svc, "harbor", None)
            _wait_experiment_jobs(harbor, _harbor_job_names(None, harbor))
            sys.exit(f"matraix experiment create: {exc}")
        exp_id = manifest.get("experimentId")
        cells = manifest.get("cells") or []
        if args.format != "json":
            print(f"Launched experiment {exp_id} ({len(cells)} arm(s)) for task {args.task}")
            for cell in cells:
                print(
                    f"  arm {cell.get('cellId')}: {cell.get('arm') or '—'}  "
                    f"job={cell.get('jobName')}"
                )
        job_names = _harbor_job_names(manifest, getattr(svc, "harbor", None))
        failed = _wait_experiment_jobs(getattr(svc, "harbor", None), job_names)
        if exp_id:
            try:
                manifest = svc.get_experiment(str(exp_id))
            except Exception:  # noqa: BLE001
                pass
        if args.format == "json":
            output.write(json.dumps(manifest, indent=2) + "\n")
        else:
            print(f"\nInspect with:  matraix experiment analyze {exp_id}", file=sys.stderr)
        if failed:
            sys.exit(1)
    except KeyboardInterrupt:
        print(
            "matraix experiment create: interrupted; writing whatever trial "
            "results are already on disk.",
            file=sys.stderr,
        )
        raise
    finally:
        _shutdown_harbor(svc)


# ---------------------------------------------------------------------------
# Parser wiring
# ---------------------------------------------------------------------------

def add_experiment_parser(subparsers: argparse._SubParsersAction) -> None:
    exp = subparsers.add_parser(
        "experiment",
        help="Design, launch, inspect, and analyze factorial experiments.",
        description=(
            "Headless parity with the Playground Experiments surface. Reuses the "
            "same service layer and statistics, so `analyze` produces the scorecard "
            "comparisons (effect sizes, CIs, BH-FDR) as text/json/csv."
        ),
    )
    exp_sub = exp.add_subparsers(dest="experiment_command", required=True)

    def _add_repo_root(p: argparse.ArgumentParser) -> None:
        p.add_argument("--repo-root", default=None, help="MatrAIx repo root (default: discovered from cwd)")

    p_list = exp_sub.add_parser("list", help="List experiment runs under experiments/runs.")
    p_list.add_argument("--format", default="text", help="text | json (default: text)")
    _add_repo_root(p_list)

    p_show = exp_sub.add_parser("show", help="Show one experiment manifest + progress.")
    p_show.add_argument("experiment_id", help="Experiment id (e.g. exp-web-compare-options-1a2b3c4d)")
    p_show.add_argument("--format", default="text", help="text | json (default: text)")
    _add_repo_root(p_show)

    p_an = exp_sub.add_parser("analyze", help="Run the statistical scorecard for an experiment.")
    p_an.add_argument("experiment_id", help="Experiment id to analyze")
    p_an.add_argument("--format", default="text", help="Comma-separated: text,json,csv (default: text)")
    p_an.add_argument("--confidence", type=float, default=0.95, help="Confidence level (default: 0.95 → alpha 0.05)")
    p_an.add_argument("--fdr", action="store_true", help="Apply Benjamini–Hochberg FDR correction across tests")
    p_an.add_argument("--slices", action="store_true", help="Include persona-attribute slice drivers")
    p_an.add_argument("-o", "--output", default=None, help="Write to a file (single format) or directory (multiple)")
    _add_repo_root(p_an)

    p_new = exp_sub.add_parser(
        "create",
        help="Launch an experiment from an experiment task and wait until every arm finishes.",
    )
    p_new.add_argument("task", help="Experiment task path (e.g. experiments/tasks/web-compare-options)")
    p_new.add_argument("--name", default=None, help="Human-readable run name")
    p_new.add_argument("--per-arm", type=int, default=None, help="Personas per arm (default: task-declared)")
    p_new.add_argument("--seed", type=int, default=42, help="Sampling seed (default: 42)")
    p_new.add_argument("--axis", default=None, choices=[None, "sut", "put"], help="Override axis (default: task-declared)")
    p_new.add_argument("--mode", default="auto", help="Execution mode: auto | force_docker | smoke (default: auto)")
    p_new.add_argument("--persona-model", default=None, help="Persona model override")
    p_new.add_argument("--persona-pool", default=None, help="Native saved/generated cohort directory (same as Playground)")
    p_new.add_argument("--persona-ids", nargs="+", default=None, help="Explicit source IDs from that cohort, shared across arms")
    p_new.add_argument("--parallel-arms", action=argparse.BooleanOptionalAction, default=True, help="Run arms concurrently; total concurrency is arms times --concurrent")
    p_new.add_argument("--agent-name", default=None, help="Web/OS agent name override")
    p_new.add_argument("--cua-backend", default=None, help="OS-app CUA backend: docker | macos | ios")
    p_new.add_argument("--concurrent", type=int, default=2, help="Concurrent trials per arm (default: 2)")
    p_new.add_argument("--format", default="text", help="text | json (default: text)")
    _add_repo_root(p_new)


def run_experiment(args: argparse.Namespace) -> None:
    handlers = {
        "list": _cmd_list,
        "show": _cmd_show,
        "analyze": _cmd_analyze,
        "create": _cmd_create,
    }
    handler = handlers.get(args.experiment_command)
    if handler is None:  # pragma: no cover - argparse enforces choices
        sys.exit("matraix experiment: unknown subcommand")
    handler(args)
