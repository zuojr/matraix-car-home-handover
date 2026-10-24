"""Descriptive source-persona contrasts; no opportunistic p-value looks."""

from collections import Counter

from .programmatic import CONTRACT, METRIC


def bounds(row, metric=METRIC):
    if row is None or row.get("score", {}).get("metric_version") != CONTRACT:
        return 0, 1
    value = row["score"].get(metric)
    if type(value) not in {bool, int} or value not in (0, 1):
        return 0, 1
    return int(value), int(value)


def summarize(plan, records):
    cases = plan["cases"]
    if set(records) - {c["id"] for c in cases}:
        raise ValueError("Unexpected observed cases")
    groups = []
    for domain in ("car", "home"):
        for i in range(1, 7):
            task = ("J" if domain == "car" else "H") + str(i)
            selected = [c for c in cases if c["domain"] == domain and c["task"] == task]
            bs = [bounds(records.get(c["id"])) for c in selected]
            groups.append(
                {
                    "domain": domain,
                    "task": task,
                    "planned": len(selected),
                    "confirmed_success": sum(b[0] for b in bs),
                    "success_rate": sum(b[0] for b in bs) / len(bs),
                    "possible_success": sum(b[1] for b in bs),
                    "missing_or_unresolved": sum(b[0] != b[1] for b in bs),
                    "partial": sum(
                        bounds(records.get(c["id"]), "feasible_partial_completion")[0]
                        for c in selected
                    ),
                }
            )
    comparisons = []
    specs = [
        ("car", "disclosure", ("C1", "C3"), ("C2", "C4"), [], METRIC),
        (
            "car",
            "priority",
            ("C1", "C2"),
            ("C3", "C4"),
            ["J1", "J2", "J3", "J6"],
            METRIC,
        ),
        ("home", "disclosure", ("C1", "C3"), ("C2", "C4"), [], METRIC),
        (
            "home",
            "priority",
            ("C1", "C2"),
            ("C3", "C4"),
            ["H1", "H5"],
            "preference_match",
        ),
    ]
    conditional = []
    for domain in ("car", "home"):
        for label, left, right, tasks, metric in [
            ("disclosure_priority1", ("C1",), ("C2",), [], METRIC),
            ("disclosure_priority2", ("C3",), ("C4",), [], METRIC),
            (
                "priority_proactive",
                ("C1",),
                ("C3",),
                ["J1", "J2", "J3", "J6"] if domain == "car" else ["H1", "H5"],
                METRIC if domain == "car" else "preference_match",
            ),
            (
                "priority_on_demand",
                ("C2",),
                ("C4",),
                ["J1", "J2", "J3", "J6"] if domain == "car" else ["H1", "H5"],
                METRIC if domain == "car" else "preference_match",
            ),
        ]:
            conditional.append((domain, label, left, right, tasks, metric))
    for domain, label, left, right, tasks, metric in specs + conditional:
        units = []
        ids = sorted({c["source_persona_id"] for c in cases if c["domain"] == domain})
        for pid in ids:
            sides = []
            for cohorts in (left, right):
                selected = [
                    c
                    for c in cases
                    if c["domain"] == domain
                    and c["source_persona_id"] == pid
                    and c["cohort"] in cohorts
                    and (not tasks or c["task"] in tasks)
                ]
                bs = [bounds(records.get(c["id"]), metric) for c in selected]
                sides.append(
                    (sum(b[0] for b in bs) / len(bs), sum(b[1] for b in bs) / len(bs))
                )
            units.append(
                {
                    "source_persona_id": pid,
                    "lower": sides[0][0] - sides[1][1],
                    "upper": sides[0][1] - sides[1][0],
                }
            )
        comparisons.append(
            {
                "domain": domain,
                "comparison": label,
                "metric": metric,
                "units": units,
                "difference_lower": sum(u["lower"] for u in units) / len(units),
                "difference_upper": sum(u["upper"] for u in units) / len(units),
                "independent_unit": "source_persona",
            }
        )
    findings = Counter()
    evidence = []
    for cid, row in records.items():
        issue_rows = row["score"].get("issues", [])
        codes = {x["code"] for x in issue_rows}
        if not codes and not row["score"][METRIC]:
            score = row["score"]
            if not row.get("ended") or not row.get("submission"):
                code = "structured_submission_missing"
            elif score.get("feasible_partial_completion"):
                code = "feasible_partial_due_to_unavailability"
            elif not score.get("goal_completed"):
                code = "goal_or_time_window_unmet"
            elif not score.get("constraints_and_plan_met"):
                code = "structured_plan_constraints_unmet"
            elif not score.get("preference_match"):
                code = "task_preference_unmet"
            else:
                code = "programmatic_success_unmet"
            codes.add(code)
        for code in sorted(codes):
            findings[code] += 1
            evidence.append(
                {
                    "case_id": cid,
                    "code": code,
                    "events": [
                        x.get("event")
                        for x in row["score"]["issues"]
                        if x["code"] == code
                    ]
                    or ([row["events"][-1]["event"]] if row.get("events") else []),
                    "record_session_id": row.get("sessionId"),
                    "observed_facets": {
                        k: row["score"].get(k)
                        for k in (
                            "goal_completed",
                            "constraints_and_plan_met",
                            "preference_match",
                            "scope_compliant",
                            "outcome",
                        )
                    },
                    "classification": "deterministic diagnostic, not an independent additional error",
                }
            )
    return {
        "groups": groups,
        "overall_comparisons": comparisons[:4],
        "conditional_comparisons": comparisons[4:],
        "issue_episode_counts": dict(findings),
        "evidence": evidence,
        "inference_enabled": False,
        "evidence_note": "Counts overlap across codes; do not sum them as independent product failures. Partial unavailability is not full task success.",
        "note": "Identification bounds are not confidence intervals. Formal N and inference remain unfrozen.",
    }
