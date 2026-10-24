"""Prospective fixed-final formal design and paired source-persona inference."""

from copy import deepcopy
import json
from pathlib import Path
import random
import shutil

from .cohort import CONDITIONS, DOMAINS, digest, load_plan, write_new

METHOD = "paired-source-percentile-bootstrap-bonferroni-v1"
PRIMARY = ("car:disclosure", "car:priority", "home:disclosure", "home:priority")


def validate_matrix(plan):
    if plan["planned_episodes"] != len(plan["cases"]) or len(
        {c["id"] for c in plan["cases"]}
    ) != len(plan["cases"]):
        raise ValueError("Planned case IDs/count differ")
    if plan["purpose"] in {"offline", "validation"}:
        return
    if plan["purpose"] == "harbor":
        arm = plan["native_arm"]
        rows = plan["cases"]
        if not rows or len({c["source_persona_id"] for c in rows}) != len(rows):
            raise ValueError("Native arm needs one episode per unique source persona")
        if any(
            c["cohort"] != arm["condition"]
            or c["boundary"] != (arm["variant"] == "boundary")
            for c in rows
        ):
            raise ValueError("Native arm differs from the declared factorial cell")
        return
    for domain in DOMAINS:
        rows = [c for c in plan["cases"] if c["domain"] == domain]
        ids = {c["source_persona_id"] for c in rows}
        if not ids:
            raise ValueError("Both domains require source personas")
        used_blocks = set()
        for pid in ids:
            selected = [c for c in rows if c["source_persona_id"] == pid]
            expected = {
                (cohort, ("J" if domain == "car" else "H") + str(i), edge)
                for cohort in CONDITIONS
                for i in range(1, 7)
                for edge in (False, True)
            }
            actual = {(c["cohort"], c["task"], c["boundary"]) for c in selected}
            blocks = {c["block"] for c in selected}
            if (
                actual != expected
                or len(selected) != 48
                or len(blocks) != 1
                or blocks & used_blocks
            ):
                raise ValueError(
                    "Each original persona must have exactly one complete paired 48-case block"
                )
            used_blocks.update(blocks)


def validate_spec(spec, plan):
    validate_matrix(plan)
    if (
        spec.get("method") != METHOD
        or spec.get("independent_unit") != "source_persona"
        or spec.get("primary_comparisons") != list(PRIMARY)
        or spec.get("alpha") != 0.05
        or spec.get("looks") != ["final"]
        or spec.get("missing") != "planned-denominator-[0,1]"
        or type(spec.get("bootstrap_replicates")) is not int
        or spec["bootstrap_replicates"] < 20000
        or not isinstance(spec.get("seed"), int)
    ):
        raise ValueError(
            "Unsupported or incomplete prospective statistical specification"
        )
    for domain in DOMAINS:
        n = len(
            {c["source_persona_id"] for c in plan["cases"] if c["domain"] == domain}
        )
        if n != spec.get("source_personas", {}).get(domain) or n < 20:
            raise ValueError(
                "Formal design needs the declared source counts (at least 20/domain); pilot is separate"
            )
    if (
        spec.get("approved") is not True
        or not str(spec.get("approval_note", "")).strip()
    ):
        raise ValueError(
            "Prospective design must have an explicit documented approval before formal execution"
        )


def validate_frozen(plan):
    freeze = plan.get("freeze")
    if not freeze or digest(freeze["spec"]) != freeze["spec_sha256"]:
        raise ValueError("A boolean is not a valid formal freeze")
    validate_spec(freeze["spec"], plan)
    if not freeze.get("sut_config") or not freeze.get("put_config"):
        raise ValueError("Frozen SUT/PUT configuration missing")


def freeze(plan_path, settings, out, spec_path):
    from .launch import configure

    plan = load_plan(plan_path)
    if (
        plan["purpose"] != "formal"
        or plan["fixture_only"]
        or plan["formal_spec_frozen"]
    ):
        raise ValueError("Freeze a new real-source formal plan only")
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    validate_spec(spec, plan)
    configs, limits = configure(settings, need_credentials=False)
    frozen = deepcopy(plan)
    frozen.update(
        formal_spec_frozen=True,
        freeze={
            "previous_plan_sha256": digest(plan),
            "spec": spec,
            "spec_sha256": digest(spec),
            "sut_config": configs["sut"].public(),
            "put_config": configs["put"].public(),
            "limits": limits,
        },
    )
    out = Path(out)
    if out.exists():
        raise ValueError("Never edit a bound plan in place")
    shutil.copytree(Path(plan_path) / "inputs", out / "inputs")
    shutil.copytree(Path(plan_path) / "identity", out / "identity")
    write_new(out / "plan.json", frozen)
    write_new(
        out / "manifest.json",
        {"protocol": plan["protocol"], "plan_sha256": digest(frozen)},
    )
    return {
        "frozen_plan": str(out),
        "planned_episodes": len(plan["cases"]),
        "model_requests": 0,
    }


def quantile(values, q):
    values = sorted(values)
    position = q * (len(values) - 1)
    lower = int(position)
    fraction = position - lower
    return (
        values[lower] * (1 - fraction)
        + values[min(lower + 1, len(values) - 1)] * fraction
    )


def infer(result, plan):
    validate_frozen(plan)
    spec = plan["freeze"]["spec"]
    tail = spec["alpha"] / (2 * len(PRIMARY))
    intervals = []
    for comparison in result["overall_comparisons"]:
        units = comparison["units"]
        rng = random.Random(spec["seed"])
        lower, upper = [], []
        for _ in range(spec["bootstrap_replicates"]):
            sample = rng.choices(units, k=len(units))
            lower.append(sum(r["lower"] for r in sample) / len(sample))
            upper.append(sum(r["upper"] for r in sample) / len(sample))
        lo, hi = quantile(lower, tail), quantile(upper, 1 - tail)
        intervals.append(
            {
                "comparison": comparison["domain"] + ":" + comparison["comparison"],
                "lower": lo,
                "upper": hi,
                "direction": "positive"
                if lo > 0
                else "negative"
                if hi < 0
                else "uncertain",
                "significant": lo > 0 or hi < 0,
                "equivalence_tested": False,
                "source_personas": len(units),
            }
        )
    return {
        "method": METHOD,
        "family_alpha": spec["alpha"],
        "intervals": intervals,
        "coverage": "approximate; paired percentile bootstrap and Bonferroni, not finite-sample exact",
        "assumptions": [
            "independent source personas from the declared simulation sampling frame",
            "the source-persona cluster bootstrap approximates sampling variation",
            "unknown outcomes lie in [0,1]; no complete-case/MCAR assumption",
        ],
        "limits": "Does not quantify sim-to-real error or causal effects of changing the SUT; no equivalence conclusion.",
    }
