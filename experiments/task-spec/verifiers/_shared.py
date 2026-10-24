"""Shared helpers for the generic experiment verifiers.

Every generic verifier (`web_generic`, `osapp_generic`, `chatbot_generic`,
`survey_generic`) reuses these to:

- locate the agent output dir and the Harbor verifier output dir,
- load the task's ``experiment.json`` (behavioral contract: outputArtifact +
  declared ``signals``),
- reflect declared ``signals`` out of the agent's output artifact into
  shared-core facets (Tier-2 behavioral extraction),
- read injected stimulus from ``MATRIX_PARAM_*`` env vars,
- (optional correctness path) read per-level ground truth from
  ``$HARBOR_VARIANT_DIR/expected.json``,
- build shared-core ``contexts`` / ``facets`` and write the
  ``verifier/structured_output.json`` envelope.

No third-party dependencies (runs inside the trial container).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------

def output_dir() -> Path:
    """Directory the agent writes its submission artifacts to."""
    return Path(os.environ.get("MATRIX_OUTPUT_DIR", "/app/output"))


def verifier_dir() -> Path:
    """Directory to write ``structured_output.json`` into.

    Mirrors the convention used by existing task verifiers: prefer
    ``HARBOR_VERIFIER_DIR``, fall back to the container default, and require an
    explicit path when running outside a trial container (local harness).
    """
    explicit = os.environ.get("HARBOR_VERIFIER_DIR")
    if explicit:
        path = Path(explicit)
        path.mkdir(parents=True, exist_ok=True)
        return path

    container_default = Path("/logs/verifier")
    try:
        container_default.mkdir(parents=True, exist_ok=True)
        return container_default
    except OSError:
        pass

    raise RuntimeError(
        "HARBOR_VERIFIER_DIR is required when running outside a Harbor trial "
        "container. Point it at jobs/<job>/<trial>/verifier for local runs."
    )


def experiment_config() -> dict[str, Any]:
    """Load the task's ``experiment.json`` (behavioral contract).

    Resolution order:
      1) ``$EXPERIMENTS_TASK_DIR/experiment.json`` (set by the experiment layer
         / test harness),
      2) the nearest ``experiment.json`` walking up from the current directory.

    Returns an empty dict when no config is found (single-variant fallback).
    """
    candidates: list[Path] = []
    raw = os.environ.get("EXPERIMENTS_TASK_DIR", "").strip()
    if raw:
        candidates.append(Path(raw) / "experiment.json")
    cwd = Path.cwd()
    for base in (cwd, *cwd.parents):
        candidates.append(base / "experiment.json")
    for path in candidates:
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict):
                return data
    return {}


def variant_dir() -> Path | None:
    """Directory holding this level's ``expected.json`` (per-level ground truth)."""
    raw = os.environ.get("HARBOR_VARIANT_DIR", "").strip()
    return Path(raw) if raw else None


def load_expected() -> dict[str, Any]:
    """Load per-level ground truth. Empty dict when no variant is configured."""
    vdir = variant_dir()
    if vdir is None:
        return {}
    path = vdir / "expected.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "expected.json root must be an object"
    return data


def param(name: str, default: str | None = None) -> str | None:
    """Read an injected stimulus value (``MATRIX_PARAM_<UPPER_NAME>``)."""
    return os.environ.get("MATRIX_PARAM_" + name.upper(), default)


# --------------------------------------------------------------------------
# Declarative signal reflection (Tier-2 behavioral extraction)
# --------------------------------------------------------------------------

def _dotted_get(obj: Any, path: str) -> Any:
    """Traverse a dotted path into nested dicts. Returns None if any hop misses."""
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _coerce(value: Any, kind: str) -> Any:
    """Coerce a raw value to the declared facet kind, or None to skip it."""
    if value is None:
        return None
    if kind == "numerical":
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return value
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    text = value if isinstance(value, str) else str(value)
    text = text.strip()
    return text or None


def reflect_signals(
    signals: list[dict[str, Any]],
    *,
    out_dir: Path | None = None,
    default_source: str | None = None,
) -> list[dict[str, Any]]:
    """Turn declared ``signals`` into shared-core contexts, grouped by ``context``.

    Each signal lifts one field out of its source artifact into a facet. Missing
    fields/artifacts are skipped silently so a partial submission still yields
    whatever signals it did produce. Facet ``key``s come straight from the
    declaration, so every level emits the same keys (the alignment contract).
    """
    base = out_dir or output_dir()
    grouped: dict[str, list[dict[str, Any]]] = {}
    cache: dict[str, Any] = {}
    for sig in signals or []:
        source = sig.get("source") or default_source
        if not source:
            continue
        if source not in cache:
            path = base / source
            cache[source] = load_json(path) if path.is_file() else None
        data = cache[source]
        if data is None:
            continue
        value = _dotted_get(data, sig.get("path", ""))
        if sig.get("reduce") == "count":
            value = len(value) if isinstance(value, (list, tuple, dict, str)) else None
        kind = sig.get("kind", "categorical")
        value = _coerce(value, kind)
        if value is None:
            continue
        key = sig["key"]
        grouped.setdefault(sig.get("context", "signals"), []).append(
            facet(key, sig.get("label", key), sig.get("role", "score"), kind, value)
        )
    contexts: list[dict[str, Any]] = []
    for ctx_type, facets in grouped.items():
        contexts.append(
            context(f"{ctx_type}.primary", ctx_type.replace("_", " ").title(), ctx_type, facets)
        )
    return contexts


# --------------------------------------------------------------------------
# Structured-output building blocks
# --------------------------------------------------------------------------

def facet(
    key: str,
    label: str,
    role: str,
    kind: str,
    value: Any,
    *,
    explains: str | None = None,
) -> dict[str, Any]:
    """One facet. ``role`` in {primary, score, evidence, explanation};
    ``kind`` in {numerical, categorical, textual}."""
    out: dict[str, Any] = {
        "key": key,
        "label": label,
        "role": role,
        "kind": kind,
        "value": value,
    }
    if explains is not None:
        out["explainsFacetKey"] = explains
    return out


def context(key: str, label: str, context_type: str, facets: list[dict[str, Any]]) -> dict[str, Any]:
    return {"key": key, "label": label, "contextType": context_type, "facets": facets}


def task_outcome_context(
    *,
    status: str,
    completion_ratio: float,
    completion_bucket: str,
    failure_reason: str = "none",
    verifier_mode: str = "artifact_exact",
    explanation: str = "",
    evidence: str = "",
) -> dict[str, Any]:
    """The shared-core ``task_outcome`` context every arm emits."""
    return context(
        "task_outcome.primary",
        "Task outcome",
        "task_outcome",
        [
            facet("outcome_status", "Outcome status", "primary", "categorical", status),
            facet("goal_completion_ratio", "Goal completion ratio", "score", "numerical", completion_ratio),
            facet("goal_completion_bucket", "Goal completion bucket", "primary", "categorical", completion_bucket),
            facet("verifier_mode", "Verifier mode", "evidence", "categorical", verifier_mode),
            facet("primary_failure_reason", "Primary failure reason", "primary", "categorical", failure_reason),
            facet("outcome_explanation", "Outcome explanation", "explanation", "textual", explanation),
            facet("completion_evidence", "Completion evidence", "evidence", "textual", evidence),
        ],
    )


# Map raw user_feedback.json keys -> shared-core user_feedback facets.
_FEEDBACK_NUMERIC = {
    "overallExperienceRating": ("overall_experience_rating", "Overall experience rating"),
    "trustLevel": ("trust_level", "Trust level"),
    "effortRating": ("effort_rating", "Effort rating"),
}
_FEEDBACK_CATEGORICAL = {
    "needConstraintSatisfaction": ("need_constraint_satisfaction", "Need or constraint satisfaction"),
    "personalPreferenceSatisfaction": ("personal_preference_satisfaction", "Personal preference satisfaction"),
}


def user_feedback_context(feedback: dict[str, Any]) -> dict[str, Any]:
    """Build the shared subjective ``user_feedback`` context from raw feedback."""
    facets: list[dict[str, Any]] = []
    for raw_key, (fkey, label) in _FEEDBACK_NUMERIC.items():
        value = feedback.get(raw_key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            facets.append(facet(fkey, label, "score", "numerical", value))
    reason = feedback.get("reason")
    if isinstance(reason, str) and reason.strip():
        facets.append(
            facet(
                "feedback_reason",
                "Feedback reason",
                "explanation",
                "textual",
                reason.strip(),
                explains="overall_experience_rating",
            )
        )
    for raw_key, (fkey, label) in _FEEDBACK_CATEGORICAL.items():
        value = feedback.get(raw_key)
        if isinstance(value, str) and value.strip():
            facets.append(facet(fkey, label, "evidence", "categorical", value.strip()))
    clarity = feedback.get("clarityOfNextStep")
    if isinstance(clarity, bool):
        facets.append(
            facet("clarity_of_next_step", "Clarity of next step", "evidence", "categorical", "true" if clarity else "false")
        )
    return context("user_feedback.primary", "User feedback", "user_feedback", facets)


# --------------------------------------------------------------------------
# I/O
# --------------------------------------------------------------------------

def load_json(path: Path) -> Any:
    assert path.is_file(), f"Missing {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def load_user_feedback() -> dict[str, Any] | None:
    path = output_dir() / "user_feedback.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def _reward_passed(contexts: list[dict[str, Any]], missing: list[str]) -> bool:
    """Derive the scalar pass/fail Harbor records as ``reward``.

    Prefer the ``task_outcome`` context's ``outcome_status`` (so a correctness
    failure with the artifact present still scores 0); fall back to a
    presence-only check when no outcome context is present.
    """
    for ctx in contexts:
        if ctx.get("contextType") != "task_outcome":
            continue
        for f in ctx.get("facets", []):
            if f.get("key") == "outcome_status":
                return f.get("value") == "passed"
    return not missing


def write_reward(passed: bool) -> Path:
    """Write ``reward.txt`` into the verifier dir.

    Harbor's verifier contract requires a ``reward.txt`` / ``reward.json`` in the
    verifier dir; without it every trial is marked errored (RewardFileNotFound)
    even when verification succeeded. Write next to ``structured_output.json``.
    """
    path = verifier_dir() / "reward.txt"
    path.write_text("1\n" if passed else "0\n", encoding="utf-8")
    return path


def write_structured_output(
    *,
    app_type: str,
    source_artifacts: dict[str, Any],
    contexts: list[dict[str, Any]],
    required_artifacts: list[str],
    missing_artifacts: list[str] | None = None,
) -> Path:
    missing = missing_artifacts or []
    payload = {
        "schemaVersion": "1.0",
        "artifactType": "matraix.trial_evaluation",
        "taskType": app_type,
        "presenceCheck": {
            "passed": len(missing) == 0,
            "requiredArtifacts": required_artifacts,
            "missingArtifacts": missing,
        },
        "sourceArtifacts": source_artifacts,
        "contexts": contexts,
    }
    path = verifier_dir() / "structured_output.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    # Harbor requires a reward file next to the structured output, or the trial
    # errors even though verification ran. Derive it from the task outcome.
    write_reward(_reward_passed(contexts, missing))
    return path


def nonempty(value: Any, field: str, *, max_len: int | None = None) -> str:
    assert isinstance(value, str) and value.strip(), f"{field} must be non-empty"
    cleaned = value.strip()
    if max_len is not None:
        assert len(cleaned) <= max_len, f"{field} must be at most {max_len} characters"
    return cleaned
