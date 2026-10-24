"""Generic survey experiment verifier.

Surveys have no correct answer: the response IS the metric. This verifier
validates the platform-produced ``survey_result.json`` shape and emits one facet
per answered question, keyed by a STABLE ``questionId`` (the alignment contract:
ids must not drift across levels). Any extra ``signals`` declared in
``experiment.json`` are reflected on top of the auto-derived per-question facets.
"""

from __future__ import annotations

import sys
from typing import Any

import _shared as sh


def _write_reward(passed: bool) -> None:
    """Harbor requires reward.txt in the verifier dir; without it every trial is
    marked errored. Write it next to ``structured_output.json`` (an absolute
    ``HARBOR_VERIFIER_DIR`` path) rather than the process cwd, which is not the
    verifier dir at run time."""
    (sh.verifier_dir() / "reward.txt").write_text(
        "1\n" if passed else "0\n", encoding="utf-8"
    )

APP_TYPE = "survey"


def _facet_for_answer(answer: dict[str, Any]) -> dict[str, Any] | None:
    qid = answer.get("questionId") or answer.get("id")
    if not isinstance(qid, str) or not qid.strip():
        return None
    value = answer.get("response", answer.get("value"))
    if isinstance(value, bool):
        return sh.facet(qid, qid, "score", "categorical", "true" if value else "false")
    if isinstance(value, (int, float)):
        return sh.facet(qid, qid, "score", "numerical", value)
    if isinstance(value, list):
        # multi-choice -> categorical per selected value handled by aggregation counts
        return sh.facet(qid, qid, "primary", "categorical", ", ".join(map(str, value)))
    if isinstance(value, str) and value.strip():
        # Heuristic: short tokens are categorical, long text is textual.
        kind = "categorical" if len(value.strip()) <= 40 else "textual"
        role = "primary" if kind == "categorical" else "explanation"
        return sh.facet(qid, qid, role, kind, value.strip())
    return None


def main() -> int:
    cfg = sh.experiment_config()
    artifact_name = cfg.get("outputArtifact") or "survey_result.json"
    artifact = sh.output_dir() / artifact_name
    if not artifact.is_file():
        sh.write_structured_output(
            app_type=APP_TYPE,
            source_artifacts={},
            contexts=[
                sh.task_outcome_context(
                    status="failed", completion_ratio=0.0, completion_bucket="none",
                    failure_reason="missing_artifact", verifier_mode="survey_response",
                    explanation=f"{artifact_name} was not produced.",
                )
            ],
            required_artifacts=[artifact_name],
            missing_artifacts=[artifact_name],
        )
        print(f"FAIL: missing {artifact_name}", file=sys.stderr)
        _write_reward(False)
        return 1

    data = sh.load_json(artifact)
    answers = data.get("answers") if isinstance(data, dict) else None
    assert isinstance(answers, list) and answers, "survey_result.answers must be a non-empty list"

    response_facets = [f for f in (_facet_for_answer(a) for a in answers if isinstance(a, dict)) if f]
    contexts = [
        sh.task_outcome_context(
            status="passed", completion_ratio=1.0, completion_bucket="complete",
            verifier_mode="survey_response",
            explanation="Survey completed with a valid answer set.",
            evidence=f"{len(response_facets)} question responses recorded.",
        ),
        sh.context("survey_response.primary", "Survey responses", "survey_response", response_facets),
    ]
    contexts.extend(sh.reflect_signals(cfg.get("signals") or [], default_source=artifact_name))

    source_artifacts: dict[str, Any] = {"taskOutput": str(artifact)}
    feedback = sh.load_user_feedback()
    if feedback is not None:
        source_artifacts["userFeedback"] = str(sh.output_dir() / "user_feedback.json")
        contexts.append(sh.user_feedback_context(feedback))

    sh.write_structured_output(
        app_type=APP_TYPE, source_artifacts=source_artifacts, contexts=contexts,
        required_artifacts=[artifact_name],
    )
    print("PASS")
    _write_reward(True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
