"""Independent native replay in the simulator service, after the agent phase."""

import argparse
import json
from pathlib import Path

from .cohort import VERSION, digest, write_new
from .programmatic import CONTRACT, METRIC, verify_record


def verify_trial(directory):
    directory = Path(directory)
    binding = json.loads((directory / "binding.json").read_text(encoding="utf-8"))
    case = binding["case"]
    if binding["protocol"] != VERSION or binding["case_sha256"] != digest(case):
        raise ValueError("Case binding changed")
    if not (directory / "record.json").exists():
        return binding, None
    record = json.loads((directory / "record.json").read_text(encoding="utf-8"))
    for k in ("case_id", "domain", "block", "task", "cohort", "boundary"):
        expected = case["id"] if k == "case_id" else case[k]
        if record.get(k) != expected:
            raise ValueError("Record attributed to another task/condition")
    evidence = {
        "reference": "reference_only",
        "model": "model",
        "validation": "api_validation",
    }[binding["mode"]]
    if (
        record.get("mode") != binding["mode"]
        or record.get("evidence_type") != evidence
        or record.get("sessionId") != binding["sessionId"]
        or record.get("source_persona_id")
        != case.get("source_persona_id", "offline-fixture")
        or record.get("persona_binding") != case.get("persona_binding", digest(case))
    ):
        raise ValueError("Evidence mode/source persona differs")
    verify_record(case, record)
    if record["score"]["metric_version"] != CONTRACT:
        raise ValueError("Legacy score cannot be relabeled")
    return binding, record


def verify_records(root, out):
    root, out = Path(root), Path(out)
    bindings = sorted(root.glob("*/binding.json"))
    if not bindings:
        raise ValueError("No sidecar trial evidence")
    rows, missing, modes = [], [], set()
    for path in bindings:
        binding, row = verify_trial(path.parent)
        modes.add(binding["mode"])
        if row is None:
            missing.append(binding["sessionId"])
        else:
            rows.append(row)
    if len(modes) != 1:
        raise ValueError("Do not pool reference and real model evidence")
    count = len(bindings)
    values = {
        "programmatic_task_success": sum(r["score"][METRIC] for r in rows) / count,
        "completed_episodes": len(rows),
        "planned_episodes": count,
        "missing_episodes": len(missing),
        "feasible_partial_completion": sum(
            r["score"]["feasible_partial_completion"] for r in rows
        ),
    }
    payload = {
        "schemaVersion": "1.0",
        "artifactType": "matraix.trial_evaluation",
        "taskType": "chatbot",
        "presenceCheck": {
            "passed": not missing,
            "requiredArtifacts": ["binding.json", "record.json"],
            "missingArtifacts": missing,
        },
        "sourceArtifacts": {"private_sidecar_records": str(root)},
        "contexts": [
            {
                "key": "journey_outcome.primary",
                "label": "Programmatic task outcome",
                "contextType": "task_outcome",
                "facets": [
                    {
                        "key": k,
                        "label": k,
                        "kind": "numerical",
                        "role": "score",
                        "value": v,
                    }
                    for k, v in values.items()
                ]
                + [
                    {
                        "key": "outcome_status",
                        "label": "Task outcome",
                        "kind": "categorical",
                        "role": "score",
                        "value": "unknown"
                        if missing
                        else rows[0]["score"]["outcome"]
                        if len(rows) == 1
                        else "complete"
                        if all(r["score"][METRIC] for r in rows)
                        else "mixed",
                    },
                    {
                        "key": "goal_completion_ratio",
                        "label": "Complete task fraction",
                        "kind": "numerical",
                        "role": "score",
                        "value": values[METRIC],
                    },
                    {
                        "key": "evidence_type",
                        "label": "Evidence type",
                        "kind": "categorical",
                        "role": "evidence",
                        "value": next(iter(modes)),
                    },
                ],
            }
        ],
    }
    write_new(out / "structured_output.json", payload)
    (out / "reward.txt").write_text(str(values[METRIC]) + "\n", encoding="utf-8")
    write_new(
        out / "replay.json",
        {
            "protocol": VERSION,
            "replayed": len(rows),
            "missing": missing,
            "no_model_calls": True,
        },
    )
    return values


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--records", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(verify_records(a.records, a.out)))


if __name__ == "__main__":
    main()
