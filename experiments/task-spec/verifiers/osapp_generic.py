"""Generic os-app experiment verifier.

Behavioral by default (mirrors web_generic):

1. Presence of the declared ``outputArtifact`` is the task_outcome check.
2. Declared ``signals`` from ``experiment.json`` are reflected into facets.
3. ``user_feedback.json`` is folded in when present.

An OPTIONAL correctness path checks ``$HARBOR_VARIANT_DIR/expected.json``
constraints verbatim (e.g. target entity / computed values). ``backend``
(docker/macos/ios) is a launch-time factor handled by the experiment layer.

Extend with side-effect / execution-profile facets in a custom verifier when the
task can compute them.
"""

from __future__ import annotations

import sys
from typing import Any

import _shared as sh

APP_TYPE = "os-app"


def main() -> int:
    cfg = sh.experiment_config()
    artifact_name = cfg.get("outputArtifact") or "result.json"
    artifact = sh.output_dir() / artifact_name

    if not artifact.is_file():
        sh.write_structured_output(
            app_type=APP_TYPE,
            source_artifacts={},
            contexts=[
                sh.task_outcome_context(
                    status="failed", completion_ratio=0.0, completion_bucket="none",
                    failure_reason="missing_artifact", verifier_mode="behavioral",
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
        constraints: dict[str, Any] = expected.get("constraints") or {}
        try:
            for ckey, cval in constraints.items():
                assert data.get(ckey) == cval, f"{ckey} must equal {cval!r}"
            outcome_ctx = sh.task_outcome_context(
                status="passed", completion_ratio=1.0, completion_bucket="complete",
                verifier_mode="constraints",
                explanation="Output artifact satisfied all configured constraints.",
                evidence=f"Checked {len(constraints)} constraint(s).",
            )
        except AssertionError as exc:
            passed = False
            failure_reason = "constraint_violation"
            err = str(exc)
            outcome_ctx = sh.task_outcome_context(
                status="failed", completion_ratio=0.0, completion_bucket="none",
                failure_reason=failure_reason, verifier_mode="constraints", explanation=err,
            )
    else:
        outcome_ctx = sh.task_outcome_context(
            status="passed", completion_ratio=1.0, completion_bucket="complete",
            verifier_mode="behavioral",
            explanation="Agent produced a well-formed output; behavioral signals reflected.",
        )

    contexts: list[dict[str, Any]] = [outcome_ctx]
    if passed:
        contexts.extend(sh.reflect_signals(cfg.get("signals") or [], default_source=artifact_name))

    source_artifacts: dict[str, Any] = {"taskOutput": str(artifact)}
    feedback = sh.load_user_feedback()
    if feedback is not None and passed:
        source_artifacts["userFeedback"] = str(sh.output_dir() / "user_feedback.json")
        contexts.append(sh.user_feedback_context(feedback))

    sh.write_structured_output(
        app_type=APP_TYPE, source_artifacts=source_artifacts, contexts=contexts,
        required_artifacts=[artifact_name],
    )
    if not passed:
        print(f"FAIL: {err}", file=sys.stderr)
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
