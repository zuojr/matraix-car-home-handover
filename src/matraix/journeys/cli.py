"""Offline preparation and explicit API execution for Car/Home journeys."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

from .cohort import DOMAINS, code_contract, digest, load_plan, prepare, write_new


def materialize(repo):
    """Self-contained Docker build context required by Harbor materialization."""
    repo = Path(repo).resolve()
    package = (
        repo / "environment/task-environments/application/chatbot-api-sidecar_journeys"
    )
    target = package / "runtime"
    if target.exists():
        contract = target / "source-contract.json"
        if (
            contract.exists()
            and json.loads(contract.read_text(encoding="utf-8")) == code_contract()
        ):
            return target
        raise ValueError(
            "Generated runtime differs; use a new checkout or remove only the reviewed runtime directory"
        )
    target.mkdir()
    dest = target / "matraix"
    dest.mkdir()
    shutil.copyfile(repo / "src/matraix/__init__.py", dest / "__init__.py")
    shutil.copytree(
        Path(__file__).parent,
        dest / "journeys",
        ignore=shutil.ignore_patterns(".cache", "__pycache__", "*.pyc"),
    )
    for name in ("Dockerfile", "requirements.txt"):
        shutil.copyfile(package / "build-assets" / name, target / name)
    write_new(target / "source-contract.json", code_contract())
    return target


def analyze(plan_path, records, out):
    from .analysis import summarize
    from .verify import verify_trial

    plan = load_plan(plan_path)
    expected = {c["id"]: c for c in plan["cases"]}
    rows, seen = {}, set()
    for path in Path(records).glob("*/binding.json"):
        binding, row = verify_trial(path.parent)
        case = binding["case"]
        cid = case["id"]
        if cid in seen or cid not in expected or digest(case) != digest(expected[cid]):
            raise ValueError("Duplicate or unplanned episode evidence")
        if binding["mode"] != "model":
            raise ValueError("Reference evidence cannot become measured success rates")
        seen.add(cid)
        if row is not None:
            rows[cid] = row
    result = summarize(plan, rows)
    result.update(
        plan_sha256=digest(plan),
        attempted=len(seen),
        unattempted=len(expected) - len(seen),
    )
    write_new(Path(out) / "descriptive.json", result)
    return result


def resolve(repo, plan_path, out, put_model):
    """Resolve one case/one original persona/one sidecar into each Harbor job."""
    import yaml

    repo, out, plan_path = (
        Path(repo).resolve(),
        Path(out).resolve(),
        Path(plan_path).resolve(),
    )
    plan = load_plan(plan_path)
    if out.exists() or not out.is_relative_to(repo):
        raise ValueError("New resolved task directory inside this checkout required")
    if plan["fixture_only"] or plan["purpose"] == "offline":
        raise ValueError("Reference fixtures cannot generate model jobs")
    if plan["purpose"] == "formal":
        raise ValueError(
            "Use execute for formal collection with its shared request ledger; Harbor recipes are pilot-only"
        )
    shared = (
        repo
        / "environment/task-environments/application/chatbot-api-sidecar_journeys/plan"
    )
    if shared.exists():
        if digest(load_plan(shared)) != digest(plan):
            raise ValueError("Another plan is mounted; use an independent checkout")
    else:
        shutil.copytree(plan_path, shared)
    for case in plan["cases"]:
        domain, task = case["domain"], case["task"].lower()
        dest = out / "tasks" / case["id"]
        shutil.copytree(repo / f"application/tasks/chat_journeys-{domain}-{task}", dest)
        cfg = yaml.safe_load((dest / "input/chatbot.yaml").read_text(encoding="utf-8"))
        cfg["runtimeDefaults"]["applicationContext"] = case["id"]
        cfg["protocol"]["sendMessage"]["staticBody"]["applicationContext"] = case["id"]
        (dest / "input/chatbot.yaml").write_text(
            yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8"
        )
        card = {
            "situation": case["initial_message"],
            "condition": case["persona"],
            "facts": case["facts"],
            "stable_profile": case["profile"],
        }
        instruction = dest / "instruction.md"
        instruction.write_text(
            instruction.read_text(encoding="utf-8")
            + "\nCurrent task card:\n"
            + json.dumps(card, ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        toml = dest / "task.toml"
        toml.write_text(
            toml.read_text(encoding="utf-8")
            + f'\n[environment.env]\nJOURNEY_MODE = "model"\nJOURNEY_SCENARIO_ID = "{case["id"]}"\nJOURNEY_MAX_SUT_CALLS = "{plan.get("freeze", {}).get("limits", {}).get("max_sut_calls_per_case", 160)}"\n',
            encoding="utf-8",
        )
        profile = (
            plan_path
            / plan["sources"][domain]["pool"]
            / Path(case["native_persona"]["source_yaml"]).name
        )
        job = {
            "job_name": case["id"],
            "jobs_dir": str(out / "jobs"),
            "n_attempts": 1,
            "n_concurrent_trials": 1,
            "retry": {"max_retries": 0},
            "environment": {"type": "docker", "delete": True},
            "verifier": {"import_path": "matraix.journeys.harbor:JourneyVerifier"},
            "agents": [
                {
                    "import_path": "matraix.journeys.agent:JourneyPersonaAPI",
                    "model_name": put_model,
                    "kwargs": {
                        "persona_path": str(profile),
                        "plan_path": str(plan_path),
                        "case_id": case["id"],
                        "max_turns": plan.get("freeze", {})
                        .get("limits", {})
                        .get("max_persona_turns", 64),
                    },
                }
            ],
            "tasks": [{"path": str(dest)}],
        }
        path = out / "recipes" / (case["id"] + ".yaml")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(job, sort_keys=False), encoding="utf-8")
    write_new(
        out / "resolved.json",
        {
            "plan_sha256": digest(plan),
            "jobs": len(plan["cases"]),
            "started": False,
            "note": "One job per source-bound episode; no cross-product of unrelated personas and tasks.",
        },
    )
    return {"jobs": len(plan["cases"]), "started": False}


def release(source, out):
    """Local package only. Official upload format/access must be checked first."""
    source, out = Path(source).resolve(), Path(out).resolve()
    if out.exists() or out.is_relative_to(source):
        raise ValueError("New output outside source required")
    run = json.loads((source / "run.json").read_text(encoding="utf-8"))
    from .cohort import VERSION

    if run.get("protocol") != VERSION or run.get("automatic_retry") is not False:
        raise ValueError("Only new, source-bound API run artifacts may be packaged")
    if (source / "STOP.json").exists():
        raise ValueError("Resolve and document stopped run before preparing release")
    for name in (
        "plan/plan.json",
        "records",
        "sut-api-records",
        "analysis/descriptive.json",
    ):
        if not (source / name).exists():
            raise ValueError(
                "Release bundle missing "
                + name
                + "; collect private raw artifacts and verified analysis first"
            )
    plan = load_plan(source / "plan")
    if (
        plan["purpose"] not in {"pilot", "formal"}
        or run.get("evidence_type") != "model"
    ):
        raise ValueError(
            "API validation/reference artifacts are never experimental releases"
        )
    if digest(plan) != run["plan_sha256"]:
        raise ValueError("Release plan differs from run")
    # Replay first; never publish an unchecked saved score.
    checked = analyze(source / "plan", source / "records", out / "validation")
    if checked["unattempted"]:
        raise ValueError(
            "Release requires an explicit missing/unattempted report before upload mapping"
        )
    shutil.copytree(source, out / "artifacts")
    hashes = {
        p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in out.rglob("*")
        if p.is_file()
    }
    write_new(
        out / "release.json",
        {
            "protocol": VERSION,
            "files": hashes,
            "uploaded": False,
            "upload_blocked": "Read actual dataset UPLOAD.md and obtain write access before mapping/publishing; this is not an official upload format.",
        },
    )
    return {"files": len(hashes), "uploaded": False}


def doctor():
    from .api import ModelConfig

    result = {
        "python": sys.version.split()[0],
        "python_313_required": sys.version_info >= (3, 13),
        "docker_available": shutil.which("docker") is not None,
        "model_requests": 0,
    }
    for role in ("sut", "put"):
        prefix = "JOURNEY_" + role.upper() + "_"
        try:
            c = ModelConfig.from_env(role)
            # Do not print URLs or secrets during environment inspection.
            result[role] = {
                "configured": True,
                "model": c.model,
                "credential_present": bool(os.getenv(c.key_env)),
            }
        except ValueError:
            result[role] = {
                "configured": False,
                "credential_present": bool(os.getenv(prefix + "API_KEY")),
            }
    try:
        from .home.native import load_source

        load_source()
        result["home_native_hashes_valid"] = True
    except Exception as exc:
        result["home_native_hashes_valid"] = False
        result["home_error_type"] = type(exc).__name__
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    m = sub.add_parser("materialize")
    m.add_argument("--repo", type=Path, default=Path.cwd())
    s = sub.add_parser("prepare")
    s.add_argument("--repo", type=Path, default=Path.cwd())
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--purpose", choices=("pilot", "formal", "offline"), default="pilot")
    s.add_argument("--fixture", action="store_true")
    s.add_argument("--seed", type=int, default=20261029)
    for domain in DOMAINS:
        s.add_argument("--" + domain + "-pool", type=Path, required=True)
        s.add_argument("--" + domain + "-ids", nargs="+", required=True)
    r = sub.add_parser("run-api")
    r.add_argument("--plan", type=Path, required=True)
    r.add_argument("--chat-url", required=True)
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--execute", action="store_true")
    a = sub.add_parser("analyze")
    a.add_argument("--plan", type=Path, required=True)
    a.add_argument("--records", type=Path, required=True)
    a.add_argument("--out", type=Path, required=True)
    b = sub.add_parser("release-local")
    b.add_argument("--source", type=Path, required=True)
    b.add_argument("--out", type=Path, required=True)
    q = sub.add_parser("resolve-harbor")
    q.add_argument("--repo", type=Path, default=Path.cwd())
    q.add_argument("--plan", type=Path, required=True)
    q.add_argument("--out", type=Path, required=True)
    q.add_argument("--put-model", required=True)
    n = sub.add_parser("setup-native")
    n.add_argument(
        "--directory", type=Path, default=Path("journey-runs/native/SimuHome")
    )
    v = sub.add_parser("validation-plan")
    v.add_argument("--repo", type=Path, default=Path.cwd())
    v.add_argument("--out", type=Path, required=True)
    v.add_argument("--persona-id", default="0042")
    x = sub.add_parser("execute")
    x.add_argument("--plan", type=Path, required=True)
    x.add_argument("--config", type=Path, required=True)
    x.add_argument("--out", type=Path, required=True)
    x.add_argument("--key-file", type=Path)
    x.add_argument("--execute", action="store_true")
    f = sub.add_parser("freeze")
    f.add_argument("--plan", type=Path, required=True)
    f.add_argument("--config", type=Path, required=True)
    f.add_argument("--spec", type=Path, required=True)
    f.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    if a.command == "doctor":
        result = doctor()
    elif a.command == "materialize":
        result = {"runtime": str(materialize(a.repo)), "model_requests": 0}
    elif a.command == "prepare":
        plan = prepare(
            a.repo,
            {d: getattr(a, d + "_pool") for d in DOMAINS},
            {d: getattr(a, d + "_ids") for d in DOMAINS},
            a.out,
            a.purpose,
            a.fixture,
            a.seed,
        )
        result = {"planned_episodes": plan["planned_episodes"], "model_requests": 0}
    elif a.command == "run-api":
        from .run import run_api

        result = run_api(a.plan, a.chat_url, a.out, execute=a.execute)
    elif a.command == "analyze":
        result = analyze(a.plan, a.records, a.out)
    elif a.command == "resolve-harbor":
        result = resolve(a.repo, a.plan, a.out, a.put_model)
    elif a.command == "setup-native":
        from .launch import setup_native

        result = setup_native(a.directory)
    elif a.command == "validation-plan":
        from .launch import validation_plan

        result = validation_plan(a.repo, a.out, a.persona_id)
    elif a.command == "execute":
        from .launch import execute

        result = execute(
            a.plan, a.config, a.out, execute_authorized=a.execute, key_file=a.key_file
        )
    elif a.command == "freeze":
        from .design import freeze

        result = freeze(a.plan, a.config, a.out, a.spec)
    else:
        result = release(a.source, a.out)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if a.command == "execute" and result["status"] != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
