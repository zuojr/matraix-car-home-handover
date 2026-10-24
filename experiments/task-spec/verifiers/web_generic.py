"""Generic web experiment verifier.

Type-level (NOT per-task). Behavioral by default:

1. Presence of the declared ``outputArtifact`` is the task_outcome check.
2. Fields listed under ``signals`` in the task's ``experiment.json`` are reflected
   into shared-core facets so arms stay comparable.
3. ``user_feedback.json`` (if the persona left feedback) is folded in.

An OPTIONAL correctness path kicks in only when a level ships ground truth
(``$HARBOR_VARIANT_DIR/expected.json``) together with ``submissionSchema`` in
``experiment.json`` — e.g. a benchmark-style "must pick the canonically correct
option" check. Most experiments never use it.

Run inside a trial container (or locally with HARBOR_VERIFIER_DIR set):

    EXPERIMENTS_TASK_DIR=<task dir> \
    MATRIX_OUTPUT_DIR=/app/output \
    HARBOR_VERIFIER_DIR=/logs/verifier \
    python web_generic.py
"""

from __future__ import annotations

import sys
from typing import Any

import _shared as sh

APP_TYPE = "web"


# --------------------------------------------------------------------------
# Optional correctness path (only when a level supplies expected.json)
# --------------------------------------------------------------------------

def _validate_candidate(candidate: Any, index: int, option_ids: dict[str, str]) -> dict[str, str]:
    prefix = f"task_options_considered[{index}]"
    assert isinstance(candidate, dict), f"{prefix} must be an object"
    subject_id = sh.nonempty(candidate.get("decision_subject_id"), f"{prefix}.decision_subject_id", max_len=64)
    assert subject_id in option_ids, f"{prefix}.decision_subject_id must be one of {sorted(option_ids)}"
    subject_label = sh.nonempty(candidate.get("decision_subject_label"), f"{prefix}.decision_subject_label", max_len=64)
    assert subject_label == option_ids[subject_id], f"{prefix}.decision_subject_label must match canonical label"
    return {"decision_subject_id": subject_id, "decision_subject_label": subject_label}


def _verify_compare_choose(data: dict[str, Any], expected: dict[str, Any]) -> None:
    """Raise AssertionError if the submission is not canonically correct."""
    option_ids: dict[str, str] = expected.get("option_ids") or {}
    assert option_ids, "compare_choose correctness requires expected.option_ids"
    constraints: dict[str, Any] = expected.get("constraints") or {}

    subject_id = sh.nonempty(data.get("decision_subject_id"), "decision_subject_id", max_len=64)
    assert subject_id in option_ids, "decision_subject_id must be a canonical option id"
    subject_label = sh.nonempty(data.get("decision_subject_label"), "decision_subject_label", max_len=64)
    assert subject_label == option_ids[subject_id], "decision_subject_label must match canonical label"
    assert data.get("decision_outcome") == "selected", "decision_outcome must be 'selected'"

    if expected.get("source_url"):
        assert data.get("task_source_url") == expected["source_url"], "task_source_url must match the configured target"
    for ckey, cval in constraints.items():
        assert data.get(ckey) == cval, f"{ckey} must equal {cval!r}"

    raw_candidates = data.get("task_options_considered")
    assert isinstance(raw_candidates, list) and raw_candidates, "task_options_considered must be a non-empty array"
    candidates = [_validate_candidate(item, i, option_ids) for i, item in enumerate(raw_candidates)]
    ids = [c["decision_subject_id"] for c in candidates]
    assert len(ids) == len(set(ids)), "candidate option ids must be distinct"
    if expected.get("require_all_options_considered"):
        assert set(ids) == set(option_ids), "must consider exactly the full option set"
    assert subject_id in ids, "selected option must appear in task_options_considered"


def _verify_constraints(data: dict[str, Any], expected: dict[str, Any]) -> None:
    for ckey, cval in (expected.get("constraints") or {}).items():
        assert data.get(ckey) == cval, f"{ckey} must equal {cval!r}"


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def main() -> int:
    cfg = sh.experiment_config()
    artifact_name = cfg.get("outputArtifact") or "submission.json"
    artifact = sh.output_dir() / artifact_name

    if not artifact.is_file():
        sh.write_structured_output(
            app_type=APP_TYPE,
            source_artifacts={},
            contexts=[
                sh.task_outcome_context(
                    status="failed",
                    completion_ratio=0.0,
                    completion_bucket="none",
                    failure_reason="missing_artifact",
                    verifier_mode="behavioral",
                    explanation=f"Expected output artifact {artifact_name} was not produced.",
                )
            ],
            required_artifacts=[artifact_name],
            missing_artifacts=[artifact_name],
        )
        print(f"FAIL: missing {artifact}", file=sys.stderr)
        return 1

    data = sh.load_json(artifact)
    assert isinstance(data, dict), f"{artifact_name} root must be an object"

    expected = sh.load_expected()
    passed = True
    failure_reason = "none"
    err = ""

    if expected:
        # Optional correctness path.
        mode = cfg.get("submissionSchema") or expected.get("mode") or "compare_choose"
        try:
            if mode == "compare_choose":
                _verify_compare_choose(data, expected)
            else:
                _verify_constraints(data, expected)
            outcome_ctx = sh.task_outcome_context(
                status="passed", completion_ratio=1.0, completion_bucket="complete",
                verifier_mode=mode,
                explanation="Submission satisfied the configured correctness contract.",
            )
        except AssertionError as exc:
            passed = False
            failure_reason = "schema_or_constraint_violation"
            err = str(exc)
            outcome_ctx = sh.task_outcome_context(
                status="failed", completion_ratio=0.0, completion_bucket="none",
                failure_reason=failure_reason, verifier_mode=mode, explanation=err,
            )
    else:
        # Behavioral default: producing a well-formed artifact IS completion.
        outcome_ctx = sh.task_outcome_context(
            status="passed", completion_ratio=1.0, completion_bucket="complete",
            verifier_mode="behavioral",
            explanation="Agent produced a well-formed submission; behavioral signals reflected.",
        )

    contexts: list[dict[str, Any]] = [outcome_ctx]

    if passed:
        contexts.extend(
            sh.reflect_signals(cfg.get("signals") or [], default_source=artifact_name)
        )

    source_artifacts: dict[str, Any] = {"taskOutput": str(artifact)}
    feedback = sh.load_user_feedback()
    if feedback is not None and passed:
        source_artifacts["userFeedback"] = str(sh.output_dir() / "user_feedback.json")
        contexts.append(sh.user_feedback_context(feedback))

    sh.write_structured_output(
        app_type=APP_TYPE,
        source_artifacts=source_artifacts,
        contexts=contexts,
        required_artifacts=[artifact_name],
    )
    if not passed:
        print(f"FAIL: {failure_reason}: {err}", file=sys.stderr)
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
