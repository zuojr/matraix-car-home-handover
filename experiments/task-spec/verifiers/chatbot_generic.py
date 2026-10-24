"""Generic chatbot experiment verifier.

Behavioral by default: success and metrics derive from the platform harness
``transcript.json`` plus the persona ``user_feedback.json``. Fields listed under
``signals`` in ``experiment.json`` are reflected into facets, and a
conversation_summary (user turn count) is always emitted.

No external ground truth is required for the common case; a goal-specific
objective belongs in a custom verifier.
"""

from __future__ import annotations

import sys
from typing import Any

import _shared as sh

APP_TYPE = "chatbot"


def _user_turn_count(transcript: Any) -> int:
    if not isinstance(transcript, list):
        turns = transcript.get("turns") if isinstance(transcript, dict) else None
        transcript = turns if isinstance(turns, list) else []
    return sum(1 for t in transcript if isinstance(t, dict) and t.get("role") == "user")


def main() -> int:
    cfg = sh.experiment_config()
    artifact_name = cfg.get("outputArtifact") or "transcript.json"
    artifact = sh.output_dir() / artifact_name
    if not artifact.is_file():
        sh.write_structured_output(
            app_type=APP_TYPE,
            source_artifacts={},
            contexts=[
                sh.task_outcome_context(
                    status="failed", completion_ratio=0.0, completion_bucket="none",
                    failure_reason="missing_artifact", verifier_mode="behavioral",
                    explanation=f"{artifact_name} was not produced.",
                )
            ],
            required_artifacts=[artifact_name],
            missing_artifacts=[artifact_name],
        )
        print(f"FAIL: missing {artifact_name}", file=sys.stderr)
        return 1

    transcript = sh.load_json(artifact)
    user_turns = _user_turn_count(transcript)

    contexts = [
        sh.task_outcome_context(
            status="passed", completion_ratio=1.0, completion_bucket="complete",
            verifier_mode="behavioral",
            explanation="Conversation completed and transcript captured.",
            evidence=f"{user_turns} user turns recorded.",
        ),
        sh.context(
            "conversation_summary.primary", "Conversation summary", "conversation_summary",
            [sh.facet("user_turn_count", "User turn count", "score", "numerical", user_turns)],
        ),
    ]
    contexts.extend(sh.reflect_signals(cfg.get("signals") or [], default_source=artifact_name))

    source_artifacts: dict[str, Any] = {"transcript": str(artifact)}
    feedback = sh.load_user_feedback()
    if feedback is not None:
        source_artifacts["userFeedback"] = str(sh.output_dir() / "user_feedback.json")
        contexts.append(sh.user_feedback_context(feedback))

    sh.write_structured_output(
        app_type=APP_TYPE, source_artifacts=source_artifacts, contexts=contexts,
        required_artifacts=[artifact_name],
    )
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
